"""Evaluation-only evidence verifier providers.

- ``MockEvidenceVerifier``: deterministic fake used to exercise the pipeline,
  validation, metrics, reporting, source-id enforcement, and supported /
  unsupported paths. Its metrics have NO semantic meaning; it is not a quality
  benchmark.
- ``DeepSeekVerifierAdapter`` and ``OpenCodeGoVerifierAdapter``: evaluation-only adapters for
  OpenAI-compatible chat-completions endpoint. It lives entirely under
  evaluation code, is never imported by production, uses temperature 0,
  requests strict structured JSON, and instructs the model to use only the
  supplied evidence.

Default execution performs ZERO network/model calls. External execution
requires an explicit opt-in (``--allow-external-api``) plus the provider's
dedicated API key. This module never prints API keys.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from app.evaluation.verifier import (
    EvidenceItem,
    MalformedVerifierOutputError,
    ReasonCode,
    VerificationDecision,
    VerifierProviderError,
    validate_decision,
)
from app.evaluation.verifier_prompt import build_verifier_messages

DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_OPENCODE_GO_MODEL = "deepseek-v4-flash"
DEFAULT_OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
OPENCODE_GO_CHAT_ENDPOINT = "/chat/completions"
EXTERNAL_PROVIDERS = frozenset({"deepseek", "opencode-go"})


def _default_mock_decision(question: str, evidence: Sequence[EvidenceItem]) -> VerificationDecision:
    """Default fake rule: supported iff at least one evidence item exists.

    This deliberately mirrors the production baseline (answer the question
    whenever retrieval returned candidates). It is NOT a semantic verifier;
    its output has no meaning beyond exercising the pipeline.
    """
    if not evidence:
        return VerificationDecision(
            supported=False,
            reason=ReasonCode.INSUFFICIENT_EVIDENCE.value,
            evidence_source_ids=[],
        )
    return VerificationDecision(
        supported=True,
        reason=ReasonCode.SUFFICIENT_EVIDENCE.value,
        evidence_source_ids=[evidence[0].source_id],
    )


class MockEvidenceVerifier:
    """Deterministic fake verifier.

    ``decision_fn`` may be injected by tests to script supported/unsupported
    outcomes. The default rule is documented as infrastructure-only.
    """

    def __init__(
        self,
        decision_fn: Callable[[str, Sequence[EvidenceItem]], VerificationDecision] | None = None,
    ):
        self._decision_fn = decision_fn or _default_mock_decision
        self._model_name = "mock-deterministic"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def verify(self, question: str, evidence: Sequence[EvidenceItem]) -> VerificationDecision:
        return self._decision_fn(question, list(evidence))


# ---------------------------------------------------------------------------
# DeepSeek (OpenAI-compatible) adapter â€” evaluation only
# ---------------------------------------------------------------------------


def parse_decision_json(text: str) -> dict[str, Any]:
    """Parse a single JSON object from model text, tolerating code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise MalformedVerifierOutputError("model output is not valid JSON") from exc
    if not isinstance(data, dict):
        raise MalformedVerifierOutputError("model output must be a JSON object")
    return data


def parse_decision_from_api_response(api_payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the decision object from a chat-completions response envelope."""
    choices = api_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise MalformedVerifierOutputError("API response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise MalformedVerifierOutputError("API response message content is empty")
    return parse_decision_json(content)


def build_chat_request(
    question: str, evidence: Sequence[EvidenceItem], model: str
) -> dict[str, Any]:
    """Request payload: temperature 0, strict structured JSON, stream off."""
    return {
        "model": model,
        "messages": build_verifier_messages(question, evidence),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "stream": False,
    }


class DeepSeekVerifierAdapter:
    """Evaluation-only verifier for an OpenAI-compatible chat-completions API.

    Makes one API call per question. Never constructed or used by default.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
        timeout: float = 60.0,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._model_name = model

    @property
    def model_name(self) -> str:
        return self._model_name

    async def verify(self, question: str, evidence: Sequence[EvidenceItem]) -> VerificationDecision:
        """Call the external API and validate the decision server-side.

        Transport and parsing failures are converted into a controlled
        :class:`VerifierProviderError` (no raw response bodies, no API keys).
        Source ids are re-validated against the supplied evidence before any
        decision is accepted.
        """
        allowed = {item.source_id for item in evidence}
        payload = build_chat_request(question, evidence, self._model)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                api_payload = response.json()
        except httpx.HTTPError as exc:
            raise VerifierProviderError("verifier API request failed") from exc
        except ValueError as exc:
            raise VerifierProviderError("verifier API returned an unreadable response") from exc
        raw = parse_decision_from_api_response(api_payload)
        return validate_decision(raw, allowed)


class OpenCodeGoVerifierAdapter(DeepSeekVerifierAdapter):
    """Evaluation-only OpenCode Go verifier using DeepSeek V4 Flash."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENCODE_GO_MODEL,
        base_url: str = DEFAULT_OPENCODE_GO_BASE_URL,
        timeout: float = 60.0,
    ):
        super().__init__(api_key=api_key, model=model, base_url=base_url, timeout=timeout)


# ---------------------------------------------------------------------------
# External-API safety gate and provider construction
# ---------------------------------------------------------------------------


def ensure_external_api_opt_in(provider: str, allow_external_api: bool) -> None:
    """Refuse external providers unless the caller explicitly opts in.

    Raises ``SystemExit`` with guidance. The mock provider requires no opt-in.
    """
    if provider in EXTERNAL_PROVIDERS and not allow_external_api:
        raise SystemExit(
            f"Provider {provider!r} makes external model API calls. Pass "
            "--allow-external-api to explicitly opt in. Default execution "
            "performs zero network/model calls."
        )


def build_verifier_provider(provider: str, model: str | None = None) -> tuple[Any, str, bool]:
    """Instantiate the requested verifier provider (never executes a model call).

    Returns ``(verifier, provider_name, external_api_used)``. External
    providers require their dedicated environment variable; keys are never printed.
    """
    if provider == "mock":
        return MockEvidenceVerifier(), "mock", False
    if provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise SystemExit(
                "Provider 'deepseek' requires the DEEPSEEK_API_KEY environment "
                "variable. The key is never printed by this tool."
            )
        selected_model = model or DEFAULT_DEEPSEEK_MODEL
        return (
            DeepSeekVerifierAdapter(api_key=api_key, model=selected_model),
            "deepseek",
            True,
        )
    if provider == "opencode-go":
        api_key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
        if not api_key:
            raise SystemExit(
                "Provider 'opencode-go' requires the OPENCODE_GO_API_KEY environment "
                "variable. The key is never printed by this tool."
            )
        selected_model = model or DEFAULT_OPENCODE_GO_MODEL
        return (
            OpenCodeGoVerifierAdapter(api_key=api_key, model=selected_model),
            "opencode-go",
            True,
        )
    raise SystemExit(f"Unknown verifier provider {provider!r}")
