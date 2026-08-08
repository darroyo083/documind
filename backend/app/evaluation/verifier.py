"""Evidence verifier protocol, decision schema, and strict output validation.

Evaluation-only. Nothing in this module is imported by production code.

The verifier answers one question:

    "Does the supplied evidence contain enough information to answer the question?"

It does NOT answer "is this statement globally true?", it never answers the
question itself, and it only ever sees the question plus the already-retrieved,
already-authorized evidence payload it is given.

This module is pure and deterministic: no I/O, no network, no model calls.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

REASON_CODES = frozenset(
    {
        "sufficient_evidence",
        "insufficient_evidence",
        "missing_requested_fact",
        "ambiguous_evidence",
    }
)

DEFAULT_SCHEMA_VERSION = "2"
SCHEMA_VERSIONS = ("1", "2")

_V2_ALLOWED_KEYS = frozenset({"supported", "evidence_source_ids", "reason"})


class ReasonCode(StrEnum):
    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    MISSING_REQUESTED_FACT = "missing_requested_fact"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"


class VerifierOutputError(ValueError):
    """Base class for controlled verifier output errors."""


class MalformedVerifierOutputError(VerifierOutputError):
    """Output violates the decision schema (bad JSON, missing keys, wrong types)."""


class UnknownEvidenceSourceError(VerifierOutputError):
    """Output references a source id not present in the supplied evidence."""


class MissingSupportingSourceError(VerifierOutputError):
    """supported=true was returned without any evidence_source_id."""


class VerifierProviderError(VerifierOutputError):
    """Controlled transport/provider failure (e.g. external API error).

    Raised instead of leaking raw HTTP exceptions out of the harness. It does
    not carry API keys or raw response bodies.
    """


@dataclass(frozen=True)
class EvidenceItem:
    """Verifier-safe metadata for one retrieved, authorized candidate.

    Only fields needed for grounding are carried. Benchmark labels, hidden
    ground truth, semantic fixture ids, evaluation splits, and cross-user data
    are deliberately absent.
    """

    source_id: str
    source_kind: str
    document_name: str
    page_number: int
    content: str
    score: float


@dataclass(frozen=True)
class VerificationDecision:
    """Structured verifier output after server-side validation."""

    supported: bool
    reason: str
    evidence_source_ids: list[str] = field(default_factory=list)


class EvidenceVerifier(Protocol):
    """Contract every evaluation verifier provider implements.

    ``verify`` is async to match the real model adapter; mock implementations
    simply return synchronously wrapped in an async coroutine.
    """

    @property
    def model_name(self) -> str: ...

    async def verify(
        self, question: str, evidence: Sequence[EvidenceItem]
    ) -> VerificationDecision: ...


def decision_to_dict(decision: VerificationDecision) -> dict[str, Any]:
    """Serialize a decision back to the raw dict form for re-validation."""
    return {
        "supported": decision.supported,
        "reason": decision.reason,
        "evidence_source_ids": list(decision.evidence_source_ids),
    }


def server_reason(supported: bool) -> str:
    """Server-derived two-value reason for a v2 decision.

    The model never supplies the reason under schema v2; the server fills it
    from ``supported`` alone. ``supported=true`` maps to
    ``sufficient_evidence`` and ``supported=false`` to ``insufficient_evidence``.
    """
    return (
        ReasonCode.SUFFICIENT_EVIDENCE.value
        if supported
        else ReasonCode.INSUFFICIENT_EVIDENCE.value
    )


def validate_decision(
    raw: dict[str, Any],
    allowed_source_ids: set[str],
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> VerificationDecision:
    """Strictly validate a parsed verifier output against the decision schema.

    Rules enforced here (never silently accepting invalid output):

    - ``raw`` must be a JSON object with a boolean ``supported`` and a reason
      code from :data:`REASON_CODES`.
    - ``evidence_source_ids`` must be a list of strings.
    - Every source id MUST be present in ``allowed_source_ids`` (the ids of the
      evidence actually supplied to the verifier). Unknown ids always fail.
    - Duplicate ids are normalized consistently: deduplicated, first occurrence
      wins, order preserved.
    - ``supported=true`` requires at least one ``evidence_source_id``.
    - ``supported=false`` requires an EMPTY ``evidence_source_ids`` list. An
      unsupported decision does not cite sources; any id returned with
      supported=false is rejected.

    Schema versions:

    - ``"1"``: the frozen v1 contract (byte-identical historical behavior).
      The model supplies ``reason`` directly.
    - ``"2"`` (default): the minimal model contract
      ``{"supported": bool, "evidence_source_ids": [str]}``. The ``reason``
      field is server-derived via :func:`server_reason`; a ``reason`` key is
      tolerated only when it carries a valid :data:`REASON_CODES` value (it is
      still overridden by the server-derived value). Any other unknown field
      is rejected.

    Raises:
        MalformedVerifierOutputError: schema violation or non-object output.
        UnknownEvidenceSourceError: a source id is not in the supplied evidence.
        MissingSupportingSourceError: supported=true with no supporting ids.
        ValueError: unknown ``schema_version``.
    """
    if schema_version == "1":
        return _validate_decision_v1(raw, allowed_source_ids)
    if schema_version == "2":
        return _validate_decision_v2(raw, allowed_source_ids)
    raise ValueError(f"unknown decision schema version {schema_version!r}")


def _validate_decision_v1(
    raw: dict[str, Any],
    allowed_source_ids: set[str],
) -> VerificationDecision:
    """Frozen v1 decision validation (byte-identical historical behavior)."""
    if not isinstance(raw, dict):
        raise MalformedVerifierOutputError("verifier output must be a JSON object")
    if "supported" not in raw:
        raise MalformedVerifierOutputError("verifier output is missing 'supported'")
    if not isinstance(raw["supported"], bool):
        raise MalformedVerifierOutputError("'supported' must be a boolean")
    if "reason" not in raw:
        raise MalformedVerifierOutputError("verifier output is missing 'reason'")
    if not isinstance(raw["reason"], str) or raw["reason"] not in REASON_CODES:
        raise MalformedVerifierOutputError(
            f"'reason' must be one of {sorted(REASON_CODES)}; got {raw['reason']!r}"
        )

    ids = raw.get("evidence_source_ids")
    if not isinstance(ids, list):
        raise MalformedVerifierOutputError("'evidence_source_ids' must be a list")
    normalized: list[str] = []
    for source_id in ids:
        if not isinstance(source_id, str):
            raise MalformedVerifierOutputError("'evidence_source_ids' entries must be strings")
        if source_id not in allowed_source_ids:
            raise UnknownEvidenceSourceError(
                f"evidence_source_id {source_id!r} is not present in the supplied evidence"
            )
        if source_id not in normalized:
            normalized.append(source_id)

    if raw["supported"] and not normalized:
        raise MissingSupportingSourceError(
            "supported=true requires at least one evidence_source_id"
        )
    if not raw["supported"] and normalized:
        raise MalformedVerifierOutputError(
            "supported=false requires evidence_source_ids to be empty"
        )

    return VerificationDecision(
        supported=raw["supported"],
        reason=raw["reason"],
        evidence_source_ids=normalized,
    )


def _validate_decision_v2(
    raw: dict[str, Any],
    allowed_source_ids: set[str],
) -> VerificationDecision:
    """Minimal model contract validation (schema v2, default).

    The model output schema is exactly ``{"supported": bool,
    "evidence_source_ids": [str]}``. Unknown extra fields are rejected. A
    ``reason`` key is tolerated only when it holds a valid
    :data:`REASON_CODES` value (the round-trip of a previously derived
    decision); the returned decision ALWAYS carries the server-derived
    two-value reason from :func:`server_reason`.
    """
    if not isinstance(raw, dict):
        raise MalformedVerifierOutputError("verifier output must be a JSON object")
    unknown = sorted(set(raw) - _V2_ALLOWED_KEYS)
    if unknown:
        raise MalformedVerifierOutputError(
            f"verifier output has unknown field(s): {unknown}"
        )
    if "supported" not in raw:
        raise MalformedVerifierOutputError("verifier output is missing 'supported'")
    if not isinstance(raw["supported"], bool):
        raise MalformedVerifierOutputError("'supported' must be a boolean")
    if "evidence_source_ids" not in raw:
        raise MalformedVerifierOutputError("verifier output is missing 'evidence_source_ids'")

    reason = raw.get("reason")
    if reason is not None and (not isinstance(reason, str) or reason not in REASON_CODES):
        raise MalformedVerifierOutputError(
            f"'reason' must be one of {sorted(REASON_CODES)}; got {reason!r}"
        )

    ids = raw["evidence_source_ids"]
    if not isinstance(ids, list):
        raise MalformedVerifierOutputError("'evidence_source_ids' must be a list")
    normalized: list[str] = []
    for source_id in ids:
        if not isinstance(source_id, str):
            raise MalformedVerifierOutputError("'evidence_source_ids' entries must be strings")
        if source_id not in allowed_source_ids:
            raise UnknownEvidenceSourceError(
                f"evidence_source_id {source_id!r} is not present in the supplied evidence"
            )
        if source_id not in normalized:
            normalized.append(source_id)

    if raw["supported"] and not normalized:
        raise MissingSupportingSourceError(
            "supported=true requires at least one evidence_source_id"
        )
    if not raw["supported"] and normalized:
        raise MalformedVerifierOutputError(
            "supported=false requires evidence_source_ids to be empty"
        )

    return VerificationDecision(
        supported=raw["supported"],
        reason=server_reason(raw["supported"]),
        evidence_source_ids=normalized,
    )
