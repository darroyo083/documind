"""Offline evaluation flow for the E1c verifiable-sufficiency spike.

Evaluation-only. Nothing here is imported by production code.

Runs the two E1c candidate architectures over direct-drive dev cases
(evidence inline, no retrieval) with a provider that speaks the proof
contracts:

- P1 (one-pass control): one provider call per case. The model returns
  ``{"supported": bool, "proofs": [{"source_id", "quote"}]}`` and the server
  verifies every quote is an exact substring of its cited source.
  ``supported=true`` requires at least one server-validated proof.
- P2 (two-pass): pass 1 is the same proof selector contract; pass 2 is an
  isolated sufficiency judge that receives ONLY the trusted question plus
  the verified proofs (quote + full canonical content of that cited source
  only). Final ``supported = (proof valid AND decision == "entailed")``.
  Fail-closed: an empty or invalid pass-1 proof means ``supported=false``
  and the case never reaches pass 2.

Every stage attempt is recorded in a call ledger
(:class:`ProofCallRecord`), and the composed per-case outcome carries the
full proof-validation and sufficiency derivation. Provider/transport
failures map to :class:`VerifierProviderError` (reused from the verifier
module) and may abort the run via ``stop_on_provider_error``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.evaluation import sufficiency_metrics
from app.evaluation.verifier import EvidenceItem, VerifierProviderError
from app.evaluation.verifier_dev_cases import case_evidence_items
from app.evaluation.verifier_proof import (
    MAX_QUOTE_LENGTH,
    PROOF_SCHEMA_VERSION,
    EvidenceProofV1,
    MalformedProofOutputError,
    MissingValidProofError,
    ProofDecisionV1,
    ProofOutputError,
    ProofValidationResultV1,
    SufficiencyDecisionV1,
    UnknownProofSourceError,
    build_verified_bundle,
    compose_supported,
    validate_proof_decision,
    validate_sufficiency_decision,
)
from app.evaluation.verifier_proof_prompts import (
    build_p1_messages,
    build_p2_judge_messages,
    build_p2_selector_messages,
)

ARCHITECTURE_P1 = "P1"
ARCHITECTURE_P2 = "P2"
VALID_ARCHITECTURES = frozenset({ARCHITECTURE_P1, ARCHITECTURE_P2})

STAGE_PROOF = "proof"
STAGE_SELECTOR = "selector"
STAGE_JUDGE = "judge"


class ProofProvider(Protocol):
    """Contract every E1c proof provider implements.

    ``complete`` returns the parsed JSON object produced by the model (the
    raw proof/judge claim; envelope extraction is the adapter's job). Model
    text that is not a JSON object raises
    :class:`MalformedProofOutputError`; transport failures raise
    :class:`VerifierProviderError`.
    """

    @property
    def model_name(self) -> str: ...

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]: ...


def parse_proof_json(text: str) -> dict[str, Any]:
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
        raise MalformedProofOutputError("model output is not valid JSON") from exc
    if not isinstance(data, dict):
        raise MalformedProofOutputError("model output must be a JSON object")
    return data


class ProofChatAdapter:
    """Evaluation-only proof provider for an OpenAI-compatible chat API.

    Uses the same transport contract as the verifier adapters: temperature
    0, ``json_object`` response format, stream off. Never constructed or
    used by default.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 60.0,
        model_name: str | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._model_name = model_name or model

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
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
            raise VerifierProviderError("proof provider API request failed") from exc
        except ValueError as exc:
            raise VerifierProviderError(
                "proof provider API returned an unreadable response"
            ) from exc
        choices = api_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise MalformedProofOutputError("API response has no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise MalformedProofOutputError("API response message content is empty")
        return parse_proof_json(content)


class MockProofProvider:
    """Deterministic scripted proof provider (offline infrastructure only).

    ``respond_fn`` may be injected to script pass-1/judge outcomes; results
    have NO semantic meaning.
    """

    def __init__(
        self,
        respond_fn: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None,
        model_name: str = "mock-proof",
    ):
        self._respond_fn = respond_fn or _default_mock_response
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return self._respond_fn(messages)


def _default_mock_response(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Default fake rule: quote the first evidence item's content verbatim.

    Dispatches on the system prompt: judge calls return an entailed verdict
    over index 0; selector/proof calls return a quote of the first evidence
    item.
    """
    system = messages[0]["content"] if messages else ""
    if "supporting_proof_indexes" in system:
        return {
            "decision": "entailed",
            "supporting_proof_indexes": [0],
            "reason": "infrastructure mock",
        }
    user = messages[-1]["content"]
    for line in user.splitlines():
        if line.startswith("[1] source_id:"):
            source_id = line.split("source_id:", 1)[1].strip()
            quote = _quote_from_user(user, source_id)
            if quote is not None:
                return {"supported": True, "proofs": [{"source_id": source_id, "quote": quote}]}
    return {"supported": False, "proofs": []}


def _quote_from_user(user: str, source_id: str) -> str | None:
    marker = f"[1] source_id: {source_id}"
    index = user.find(marker)
    if index == -1:
        return None
    content_marker = "content:\n"
    start = user.find(content_marker, index)
    if start == -1:
        return None
    start += len(content_marker)
    fence_marker = "    <document-text>\n"
    if user.startswith(fence_marker, start):
        start += len(fence_marker)
    end = user.find("\n    </document-text>", start)
    if end == -1:
        return None
    content = user[start:end]
    quote = content[: min(len(content), 80)]
    if not quote.strip():
        return None
    return quote


@dataclass(frozen=True)
class ProofCallRecord:
    """One ledger entry per stage attempt."""

    case_id: str
    architecture: str
    stage: str
    attempted: bool
    successful: bool
    provider_failure: bool
    structural_valid: bool
    proof_valid: bool
    semantic_decision: str | None = None


@dataclass(frozen=True)
class ProofCaseOutcome:
    """Composed per-case outcome with the full supported derivation."""

    case_id: str
    architecture: str
    category: str
    answerable: bool
    supported: bool
    invalid: bool
    error_kind: str | None = None
    error: str | None = None
    proof: ProofDecisionV1 | None = None
    sufficiency: SufficiencyDecisionV1 | None = None


@dataclass
class ProofEvaluation:
    outcomes: list[ProofCaseOutcome]
    ledger: list[ProofCallRecord]
    metrics: dict[str, Any]
    invalid_outputs: list[ProofCaseOutcome]
    false_supports: list[ProofCaseOutcome]
    false_rejections: list[ProofCaseOutcome]
    planned_calls: int
    verifier_calls: int = 0


class ProofProviderAbortError(RuntimeError):
    """Fail-fast provider error carrying results captured before the failure."""

    def __init__(self, case_id: str, evaluation: ProofEvaluation):
        super().__init__(f"proof provider failed for case {case_id}")
        self.case_id = case_id
        self.evaluation = evaluation


def _error_kind(error: ProofOutputError) -> str:
    if isinstance(error, UnknownProofSourceError):
        return "evidence_source_validation"
    if isinstance(error, MissingValidProofError):
        return "proof_invalid"
    return "malformed_output"


def _record(
    case_id: str,
    architecture: str,
    stage: str,
    *,
    attempted: bool = True,
    successful: bool = True,
    provider_failure: bool = False,
    structural_valid: bool = True,
    proof_valid: bool = True,
    semantic_decision: str | None = None,
) -> ProofCallRecord:
    return ProofCallRecord(
        case_id=case_id,
        architecture=architecture,
        stage=stage,
        attempted=attempted,
        successful=successful,
        provider_failure=provider_failure,
        structural_valid=structural_valid,
        proof_valid=proof_valid,
        semantic_decision=semantic_decision,
    )


async def run_proof_evaluation(
    cases: Sequence[dict[str, Any]],
    provider: ProofProvider,
    architecture: str,
    *,
    stop_on_provider_error: bool = False,
    max_quote_length: int = MAX_QUOTE_LENGTH,
) -> ProofEvaluation:
    """Run the P1 or P2 architecture over direct-drive cases.

    Invalid outputs are never silently accepted: they are captured per case
    as controlled evaluation errors (recorded in the ledger and the
    ``invalid_outputs`` list) and can never become ``supported``.
    """
    if architecture not in VALID_ARCHITECTURES:
        raise ValueError(f"unknown E1c architecture {architecture!r}")
    outcomes: list[ProofCaseOutcome] = []
    ledger: list[ProofCallRecord] = []
    verifier_calls = 0
    for case in sorted(cases, key=lambda c: c["id"]):
        case_id = case["id"]
        evidence = case_evidence_items(case)
        sources = {item.source_id: item.content for item in evidence}
        if architecture == ARCHITECTURE_P1:
            outcome, records, stage_calls = await _run_p1_case(
                case_id, case["question"], evidence, sources, provider, max_quote_length
            )
        else:
            outcome, records, stage_calls = await _run_p2_case(
                case_id, case["question"], evidence, sources, provider, max_quote_length
            )
        ledger.extend(records)
        verifier_calls += stage_calls
        final = ProofCaseOutcome(
            case_id=case_id,
            architecture=architecture,
            category=case["category"],
            answerable=case["expected_supported"],
            supported=outcome.supported,
            invalid=outcome.invalid,
            error_kind=outcome.error_kind,
            error=outcome.error,
            proof=outcome.proof,
            sufficiency=outcome.sufficiency,
        )
        outcomes.append(final)
        if stop_on_provider_error and final.invalid and final.error_kind == "provider_error":
            raise ProofProviderAbortError(
                case_id, _build_evaluation(outcomes, ledger, verifier_calls)
            )

    return _build_evaluation(outcomes, ledger, verifier_calls)


async def _run_p1_case(
    case_id: str,
    question: str,
    evidence: Sequence[EvidenceItem],
    sources: dict[str, str],
    provider: ProofProvider,
    max_quote_length: int,
) -> tuple[ProofCaseOutcome, list[ProofCallRecord], int]:
    """One-pass P1: single proof-generation call, no judge."""
    records: list[ProofCallRecord] = []
    try:
        raw = await provider.complete(build_p1_messages(question, evidence))
    except VerifierProviderError as error:
        records.append(
            _record(case_id, ARCHITECTURE_P1, STAGE_PROOF, successful=False, provider_failure=True)
        )
        return _invalid_outcome(case_id, "provider_error", str(error)), records, 1
    except MalformedProofOutputError as error:
        records.append(
            _record(case_id, ARCHITECTURE_P1, STAGE_PROOF, successful=True, structural_valid=False)
        )
        return _invalid_outcome(case_id, "malformed_output", str(error)), records, 1
    try:
        decision = validate_proof_decision(raw, sources, max_quote_length=max_quote_length)
    except ProofOutputError as error:
        records.append(
            _record(
                case_id,
                ARCHITECTURE_P1,
                STAGE_PROOF,
                successful=True,
                structural_valid=True,
                proof_valid=False,
            )
        )
        return _invalid_outcome(case_id, _error_kind(error), str(error)), records, 1
    records.append(
        _record(
            case_id,
            ARCHITECTURE_P1,
            STAGE_PROOF,
            successful=True,
            structural_valid=True,
            proof_valid=bool(decision.proofs),
            semantic_decision="supported" if decision.supported else "unsupported",
        )
    )
    return (
        ProofCaseOutcome(
            case_id=case_id,
            architecture=ARCHITECTURE_P1,
            category="",
            answerable=False,
            supported=decision.supported,
            invalid=False,
            proof=decision,
        ),
        records,
        1,
    )


async def _run_p2_case(
    case_id: str,
    question: str,
    evidence: Sequence[EvidenceItem],
    sources: dict[str, str],
    provider: ProofProvider,
    max_quote_length: int,
) -> tuple[ProofCaseOutcome, list[ProofCallRecord], int]:
    """Two-pass P2: proof selector, then isolated sufficiency judge."""
    records: list[ProofCallRecord] = []
    try:
        raw = await provider.complete(build_p2_selector_messages(question, evidence))
    except VerifierProviderError as error:
        records.append(
            _record(
                case_id, ARCHITECTURE_P2, STAGE_SELECTOR, successful=False, provider_failure=True
            )
        )
        return _invalid_outcome(case_id, "provider_error", str(error)), records, 1
    except MalformedProofOutputError as error:
        records.append(
            _record(
                case_id,
                ARCHITECTURE_P2,
                STAGE_SELECTOR,
                successful=True,
                structural_valid=False,
            )
        )
        # Fail-closed: an invalid pass-1 proof never reaches pass 2.
        return _invalid_outcome(case_id, "malformed_output", str(error)), records, 1
    try:
        decision = validate_proof_decision(raw, sources, max_quote_length=max_quote_length)
    except ProofOutputError as error:
        records.append(
            _record(
                case_id,
                ARCHITECTURE_P2,
                STAGE_SELECTOR,
                successful=True,
                structural_valid=True,
                proof_valid=False,
            )
        )
        # Fail-closed: empty/invalid pass-1 proof => supported=false, no judge call.
        return _invalid_outcome(case_id, _error_kind(error), str(error)), records, 1

    if not decision.supported:
        records.append(
            _record(
                case_id,
                ARCHITECTURE_P2,
                STAGE_SELECTOR,
                successful=True,
                structural_valid=True,
                proof_valid=False,
                semantic_decision="unsupported",
            )
        )
        return (
            ProofCaseOutcome(
                case_id=case_id,
                architecture=ARCHITECTURE_P2,
                category="",
                answerable=False,
                supported=False,
                invalid=False,
                proof=decision,
            ),
            records,
            1,
        )

    records.append(
        _record(
            case_id,
            ARCHITECTURE_P2,
            STAGE_SELECTOR,
            successful=True,
            structural_valid=True,
            proof_valid=True,
            semantic_decision="supported",
        )
    )
    bundle = build_verified_bundle(decision)
    try:
        judge_raw = await provider.complete(build_p2_judge_messages(question, bundle, sources))
    except VerifierProviderError as error:
        records.append(
            _record(case_id, ARCHITECTURE_P2, STAGE_JUDGE, successful=False, provider_failure=True)
        )
        return _invalid_outcome(case_id, "provider_error", str(error)), records, 2
    except MalformedProofOutputError as error:
        records.append(
            _record(case_id, ARCHITECTURE_P2, STAGE_JUDGE, successful=True, structural_valid=False)
        )
        return _invalid_outcome(case_id, "malformed_output", str(error)), records, 2
    try:
        sufficiency = validate_sufficiency_decision(judge_raw, len(bundle.proofs))
    except ProofOutputError as error:
        records.append(
            _record(
                case_id,
                ARCHITECTURE_P2,
                STAGE_JUDGE,
                successful=True,
                structural_valid=True,
                proof_valid=False,
            )
        )
        return _invalid_outcome(case_id, _error_kind(error), str(error)), records, 2
    records.append(
        _record(
            case_id,
            ARCHITECTURE_P2,
            STAGE_JUDGE,
            successful=True,
            structural_valid=True,
            proof_valid=True,
            semantic_decision=sufficiency.decision,
        )
    )
    return (
        ProofCaseOutcome(
            case_id=case_id,
            architecture=ARCHITECTURE_P2,
            category="",
            answerable=False,
            supported=compose_supported(decision, sufficiency),
            invalid=False,
            proof=decision,
            sufficiency=sufficiency,
        ),
        records,
        2,
    )


def _invalid_outcome(
    case_id: str,
    error_kind: str,
    error: str,
) -> ProofCaseOutcome:
    return ProofCaseOutcome(
        case_id=case_id,
        architecture="",
        category="",
        answerable=False,
        supported=False,
        invalid=True,
        error_kind=error_kind,
        error=error,
    )


def _build_evaluation(
    outcomes: list[ProofCaseOutcome],
    ledger: list[ProofCallRecord],
    verifier_calls: int,
) -> ProofEvaluation:
    invalid_outputs = [o for o in outcomes if o.invalid]
    false_supports = [o for o in outcomes if not o.invalid and not o.answerable and o.supported]
    false_rejections = [o for o in outcomes if not o.invalid and o.answerable and not o.supported]
    valid = [o for o in outcomes if not o.invalid]
    metrics = {
        "overall": sufficiency_metrics.classification_metrics(
            [o.answerable for o in valid],
            [bool(o.supported) for o in valid],
        )
    }
    planned_calls = sum(2 if o.architecture == ARCHITECTURE_P2 else 1 for o in outcomes)
    return ProofEvaluation(
        outcomes=outcomes,
        ledger=ledger,
        metrics=metrics,
        invalid_outputs=invalid_outputs,
        false_supports=false_supports,
        false_rejections=false_rejections,
        planned_calls=planned_calls,
        verifier_calls=verifier_calls,
    )


# ---------------------------------------------------------------------------
# Serialization / report helpers
# ---------------------------------------------------------------------------


def proof_decision_to_dict(decision: ProofDecisionV1) -> dict[str, Any]:
    return {
        "supported": decision.supported,
        "proofs": [_proof_to_dict(p) for p in decision.proofs],
        "invalid_proofs": [_invalid_proof_to_dict(p) for p in decision.invalid_proofs],
    }


def _proof_to_dict(proof: EvidenceProofV1) -> dict[str, Any]:
    return {
        "source_id": proof.source_id,
        "quote": proof.quote,
        "start_offset": proof.start_offset,
        "end_offset": proof.end_offset,
        "status": proof.status,
    }


def _invalid_proof_to_dict(proof: ProofValidationResultV1) -> dict[str, Any]:
    return {
        "source_id": proof.source_id,
        "quote": proof.quote,
        "status": proof.status,
        "reason": proof.reason,
    }


def sufficiency_to_dict(decision: SufficiencyDecisionV1) -> dict[str, Any]:
    return {
        "decision": decision.decision,
        "supporting_proof_indexes": list(decision.supporting_proof_indexes),
        "reason": decision.reason,
    }


def call_record_to_dict(record: ProofCallRecord) -> dict[str, Any]:
    return {
        "case_id": record.case_id,
        "architecture": record.architecture,
        "stage": record.stage,
        "attempted": record.attempted,
        "successful": record.successful,
        "provider_failure": record.provider_failure,
        "structural_valid": record.structural_valid,
        "proof_valid": record.proof_valid,
        "semantic_decision": record.semantic_decision,
    }


def outcome_to_dict(outcome: ProofCaseOutcome) -> dict[str, Any]:
    data: dict[str, Any] = {
        "case_id": outcome.case_id,
        "architecture": outcome.architecture,
        "category": outcome.category,
        "answerable": outcome.answerable,
        "supported": outcome.supported,
        "invalid": outcome.invalid,
        "final_supported_derivation": _derivation_text(outcome),
    }
    if outcome.error_kind is not None:
        data["error_kind"] = outcome.error_kind
    if outcome.error is not None:
        data["error"] = outcome.error
    if outcome.proof is not None:
        data["proof_decision"] = proof_decision_to_dict(outcome.proof)
    if outcome.sufficiency is not None:
        data["sufficiency_decision"] = sufficiency_to_dict(outcome.sufficiency)
    return data


def _derivation_text(outcome: ProofCaseOutcome) -> str:
    if outcome.proof is None:
        return "supported=false (fail-closed: no valid stage-1 proof, no pass-2 call)"
    if outcome.proof.supported and outcome.sufficiency is None:
        return "supported=stage-1 decision (P1 one-pass; >=1 server-validated proof)"
    if outcome.proof.supported and outcome.sufficiency is not None:
        judge = outcome.sufficiency.decision
        return (
            f"supported=(stage-1 proof valid AND judge decision==entailed); "
            f"judge decided {judge!r} => {outcome.supported}"
        )
    return "supported=false (stage-1 decision was unsupported)"


def build_proof_json_report(
    *,
    architecture: str,
    dataset_path: str,
    dataset_version: str,
    provider: str,
    model: str,
    external_api: bool,
    runtime_seconds: float | None,
    git_commit: str | None,
    evaluation: ProofEvaluation,
    max_calls: int | None = None,
) -> dict[str, Any]:
    """Assemble the machine-readable E1c spike report."""
    benchmark: dict[str, Any] = {
        "kind": "e1c_verifiable_sufficiency",
        "proof_schema_version": PROOF_SCHEMA_VERSION,
        "architecture": architecture,
        "dataset_version": dataset_version,
        "dataset_path": str(dataset_path),
        "provider": provider,
        "model": model,
        "external_api": external_api,
        "planned_calls": evaluation.planned_calls,
        "verifier_calls": evaluation.verifier_calls,
        "runtime_seconds": round(runtime_seconds, 2) if runtime_seconds is not None else None,
        "git_commit": git_commit,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if max_calls is not None:
        benchmark["max_calls_budget"] = max_calls
    return {
        "benchmark": benchmark,
        "methodology": {
            "proof_contract": (
                "supported=true requires at least one server-validated proof: the "
                "quote must be an EXACT substring of its cited source under minimal "
                "canonicalization (CRLF/CR -> LF only). No case folding, no "
                "whitespace collapsing, no fuzzy matching."
            ),
            "p1_one_pass": (
                "P1 control: one provider call per case; the composed supported "
                "decision is exactly the stage-1 decision with >=1 valid proof."
            ),
            "p2_two_pass": (
                "P2 primary hypothesis: pass 1 selects exact quotes (server-verified); "
                "pass 2 is an isolated sufficiency judge receiving ONLY the question "
                "plus the verified proofs (quote + full content of that cited source "
                "only). Final supported=(proof valid AND decision==entailed). "
                "Fail-closed: empty/invalid pass-1 proof => supported=false without "
                "pass 2."
            ),
            "isolation_guarantee": (
                "The pass-2 payload is built SERVER-SIDE from verified proofs only; "
                "no sibling chunk text, no raw evidence bundle, and no evaluation "
                "metadata can appear in the judge input by construction."
            ),
        },
        "metrics": evaluation.metrics,
        "call_ledger": [call_record_to_dict(r) for r in evaluation.ledger],
        "outcomes": [
            outcome_to_dict(o) for o in sorted(evaluation.outcomes, key=lambda o: o.case_id)
        ],
        "invalid_outputs": [outcome_to_dict(o) for o in evaluation.invalid_outputs],
        "false_supports": [outcome_to_dict(o) for o in evaluation.false_supports],
        "false_rejections": [outcome_to_dict(o) for o in evaluation.false_rejections],
    }


def render_proof_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    lines: list[str] = []
    lines.append("# E1c Verifiable Sufficiency Spike (proof contract)")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Proof schema version: {benchmark['proof_schema_version']} (e1c-proof-1)")
    lines.append(f"- Architecture: {benchmark['architecture']}")
    lines.append(f"- Dataset: {benchmark['dataset_path']} ({benchmark['dataset_version']})")
    lines.append(f"- Provider: {benchmark['provider']} ({benchmark['model']})")
    lines.append(f"- External API calls: {benchmark['external_api']}")
    lines.append(f"- Planned calls: {benchmark['planned_calls']}")
    lines.append(f"- Verifier calls: {benchmark['verifier_calls']}")
    if benchmark.get("max_calls_budget") is not None:
        lines.append(f"- Max calls budget: {benchmark['max_calls_budget']}")
    if benchmark.get("runtime_seconds") is not None:
        lines.append(f"- Runtime: {benchmark['runtime_seconds']}s")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    for key, value in report.get("methodology", {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Call ledger")
    lines.append("")
    lines.append(
        "| case_id | architecture | stage | attempted | successful | provider_failure "
        "| structural_valid | proof_valid | semantic_decision |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for record in report["call_ledger"]:
        lines.append(
            f"| {record['case_id']} | {record['architecture']} | {record['stage']} | "
            f"{record['attempted']} | {record['successful']} | {record['provider_failure']} | "
            f"{record['structural_valid']} | {record['proof_valid']} | "
            f"{record['semantic_decision'] or ''} |"
        )
    lines.append("")
    lines.append("## Per-case outcomes")
    lines.append("")
    for outcome in report["outcomes"]:
        lines.append(f"### {outcome['case_id']} ({outcome['category']})")
        lines.append("")
        lines.append(f"- Answerable: {outcome['answerable']}")
        lines.append(f"- Final supported: {outcome['supported']}")
        lines.append(f"- Invalid: {outcome['invalid']}")
        if outcome.get("error_kind"):
            lines.append(f"- Error kind: {outcome['error_kind']}")
        if outcome.get("error"):
            lines.append(f"- Error: {outcome['error']}")
        lines.append(f"- Derivation: {outcome['final_supported_derivation']}")
        if "proof_decision" in outcome:
            proof = outcome["proof_decision"]
            lines.append(
                f"- Stage-1 proof: supported={proof['supported']}, "
                f"valid proofs={len(proof['proofs'])}, "
                f"invalid proofs={len(proof['invalid_proofs'])}"
            )
            for invalid in proof["invalid_proofs"]:
                lines.append(
                    f"  - dropped: {invalid['source_id']} status={invalid['status']} "
                    f"({invalid['reason']})"
                )
        if "sufficiency_decision" in outcome:
            sufficiency = outcome["sufficiency_decision"]
            lines.append(
                f"- Stage-2 judge: decision={sufficiency['decision']}, "
                f"supporting indexes={sufficiency['supporting_proof_indexes']}"
            )
        lines.append("")
    lines.append("## Metrics")
    lines.append("")
    overall = report["metrics"].get("overall", {})
    if overall:
        for key in (
            "answerable_retention",
            "unsupported_detection",
            "balanced_accuracy",
            "accuracy",
            "false_support_rate",
            "false_rejection_rate",
        ):
            if key in overall:
                lines.append(f"- {key.replace('_', ' ').title()}: {overall[key]:.3f}")
    lines.append("")
    lines.append("## Invalid outputs")
    lines.append("")
    if not report["invalid_outputs"]:
        lines.append("None.")
    for outcome in report["invalid_outputs"]:
        lines.append(
            f"- {outcome['case_id']}: {outcome.get('error_kind')} - {outcome.get('error')}"
        )
    lines.append("")
    return "\n".join(lines)
