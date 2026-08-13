"""Server-side Attribute-Binding (AB2) contract for the verifier finalization goal.

Evaluation-only. Nothing in this module is imported by production code.

AB2 upgrades the RF1 answerability stage into a STRUCTURED independent fact
extraction that binds the requested subject/attribute to the candidate value:

- Stage 1 reuses :class:`~app.evaluation.verifier_requested_fact.RequestedFactV1`
  (the semantic target derived from the trusted question ONLY) unchanged.
- Stage 2 reuses the E1c/RF1 exact-quote proof contract unchanged.
- Stage 3 (NEW) produces an :class:`ExtractedFactV1`: the model independently
  extracts a declarative fact ``{subject, attribute, value, value_kind,
  polarity}`` from the VERIFIED PROOFS ONLY. The extractor never sees the
  candidate/expected answer or any evaluation label.

The load-bearing invariant is polarity + explicit attribute binding:

- For a VALUE question (``requires_explicit_value=true``) ``supported`` requires
  a ``fact_extracted`` status, an affirmative polarity, a non-empty value whose
  canonicalized text is an EXACT substring of a server-verified proof quote,
  and non-empty subject/attribute fields. An absence/negation/unspecified
  polarity, a missing field, or an unanchorable value is deterministically NOT
  supported.
- For an EXISTENCE/BOOLEAN question the polarity itself is the answer
  (``affirmative``/``negative``) and no value is extracted.

All checks here are pure schema/enum/substring operations: no fuzzy matching,
no semantic rewriting, no lexical blacklist, no I/O, no model calls, no
network. Same input bytes, same output bytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.evaluation.verifier_proof import (
    ProofDecisionV1,
    UnknownProofSourceError,
    VerifiedProofBundleV1,
    canonical_sources,
    canonicalize,
)
from app.evaluation.verifier_requested_fact import RequestedFactV1

EXTRACTED_FACT_SCHEMA_VERSION = "extracted_fact_v1"
MAX_EXTRACTED_FIELD_LENGTH = 500
MAX_VALUE_LENGTH = 2000

FACT_STATUS_EXTRACTED = "fact_extracted"
FACT_STATUS_NO_FACT = "no_fact"
FACT_STATUSES = frozenset({FACT_STATUS_EXTRACTED, FACT_STATUS_NO_FACT})

EXTRACTED_VALUE_KIND_NUMERIC = "numeric"
EXTRACTED_VALUE_KIND_DATE_OR_TIME = "date_or_time"
EXTRACTED_VALUE_KIND_ENTITY = "entity"
EXTRACTED_VALUE_KIND_TEXT = "text"
EXTRACTED_VALUE_KIND_LIST = "list"
EXTRACTED_VALUE_KINDS = frozenset(
    {
        EXTRACTED_VALUE_KIND_NUMERIC,
        EXTRACTED_VALUE_KIND_DATE_OR_TIME,
        EXTRACTED_VALUE_KIND_ENTITY,
        EXTRACTED_VALUE_KIND_TEXT,
        EXTRACTED_VALUE_KIND_LIST,
    }
)

POLARITY_AFFIRMATIVE = "affirmative"
POLARITY_NEGATIVE = "negative"
POLARITY_UNSPECIFIED = "unspecified"
EXTRACTED_POLARITIES = frozenset({POLARITY_AFFIRMATIVE, POLARITY_NEGATIVE, POLARITY_UNSPECIFIED})

EXTRACTED_FACT_ALLOWED_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "subject",
        "attribute",
        "value",
        "value_kind",
        "polarity",
        "fact_anchors",
        "reason",
    }
)

CHECK_FAILURE_VALUE_NOT_ANCHORED = "value_not_anchored"
CHECK_FAILURE_POLARITY_NOT_AFFIRMATIVE = "polarity_not_affirmative"


class ExtractedFactOutputError(ValueError):
    """Base class for controlled extracted-fact output errors."""


class MalformedExtractedFactError(ExtractedFactOutputError):
    """Output violates the ExtractedFactV1 schema (bad keys, wrong types, bad enums)."""


class ExtractedFactAnchoringError(ExtractedFactOutputError):
    """A server-validated proof no longer matches its cited source.

    Raised only by invariant re-verification (mirrors ``AnswerAnchoringError``).
    """


@dataclass(frozen=True)
class ExtractedFactV1:
    """A declarative fact independently extracted from verified evidence.

    ``status=fact_extracted`` carries subject/attribute (+ value for a value
    question). ``polarity`` records whether the fact is affirmed, negated, or
    left unspecified. ``anchored`` is a server-derived measurement: for a value
    question it means the value is an exact substring of a verified proof quote;
    for an existence/boolean question it means at least one fact anchor is
    present.
    """

    status: str
    subject: str | None
    attribute: str | None
    value: str | None
    value_kind: str | None
    polarity: str
    fact_anchors: list[int]
    anchored: bool
    check_failures: list[str]
    reason: str = ""


@dataclass(frozen=True)
class AttributeBindingDecisionV1:
    """Composed AB2 decision: requested fact + proof + extracted fact."""

    fact: RequestedFactV1
    proof: ProofDecisionV1
    extracted: ExtractedFactV1 | None = None
    supported: bool = False


def _require_str_field(raw: dict[str, Any], key: str) -> None:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MalformedExtractedFactError(f"'{key}' must be a non-empty string")
    if len(value) > MAX_EXTRACTED_FIELD_LENGTH:
        raise MalformedExtractedFactError(
            f"'{key}' exceeds the maximum length of {MAX_EXTRACTED_FIELD_LENGTH} characters"
        )


def _parse_anchors(raw: dict[str, Any], bundle: VerifiedProofBundleV1) -> list[int]:
    anchors_raw = raw.get("fact_anchors")
    if not isinstance(anchors_raw, list):
        raise MalformedExtractedFactError("'fact_anchors' must be a list")
    anchors: list[int] = []
    for index in anchors_raw:
        if not isinstance(index, int) or isinstance(index, bool):
            raise MalformedExtractedFactError("'fact_anchors' entries must be integers")
        if index < 0 or index >= len(bundle.proofs):
            raise MalformedExtractedFactError(
                f"fact anchor index {index} is out of range for {len(bundle.proofs)} proof(s)"
            )
        if index not in anchors:
            anchors.append(index)
    return anchors


def validate_extracted_fact(
    raw: dict[str, Any],
    bundle: VerifiedProofBundleV1,
    fact: RequestedFactV1,
) -> ExtractedFactV1:
    """Strictly validate a parsed stage-3 extracted-fact output.

    Raises:
        MalformedExtractedFactError: schema/enum/cross-field violation.
    """
    if not isinstance(raw, dict):
        raise MalformedExtractedFactError("extracted-fact output must be a JSON object")
    unknown = sorted(set(raw) - EXTRACTED_FACT_ALLOWED_KEYS)
    if unknown:
        raise MalformedExtractedFactError(f"extracted-fact output has unknown field(s): {unknown}")
    if raw.get("schema_version") != EXTRACTED_FACT_SCHEMA_VERSION:
        raise MalformedExtractedFactError(
            f"'schema_version' must be {EXTRACTED_FACT_SCHEMA_VERSION!r}"
        )

    status = raw.get("status")
    if status not in FACT_STATUSES:
        raise MalformedExtractedFactError(f"'status' must be one of {sorted(FACT_STATUSES)}")
    polarity = raw.get("polarity")
    if polarity not in EXTRACTED_POLARITIES:
        raise MalformedExtractedFactError(
            f"'polarity' must be one of {sorted(EXTRACTED_POLARITIES)}"
        )
    value_kind = raw.get("value_kind")
    if value_kind is not None and value_kind not in EXTRACTED_VALUE_KINDS:
        raise MalformedExtractedFactError(
            f"'value_kind' must be one of {sorted(EXTRACTED_VALUE_KINDS)} or null"
        )

    value = raw.get("value")
    if value is not None and not isinstance(value, str):
        raise MalformedExtractedFactError("'value' must be a string or null")
    subject = raw.get("subject")
    if subject is not None and not isinstance(subject, str):
        raise MalformedExtractedFactError("'subject' must be a string or null")
    attribute = raw.get("attribute")
    if attribute is not None and not isinstance(attribute, str):
        raise MalformedExtractedFactError("'attribute' must be a string or null")

    anchors = _parse_anchors(raw, bundle)
    reason = raw.get("reason")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise MalformedExtractedFactError("'reason' must be a string")

    check_failures: list[str] = []
    if status == FACT_STATUS_EXTRACTED:
        _require_str_field({"subject": subject}, "subject")
        _require_str_field({"attribute": attribute}, "attribute")
        if polarity == POLARITY_UNSPECIFIED:
            raise MalformedExtractedFactError(
                "status=fact_extracted requires a non-unspecified polarity"
            )
        if not anchors:
            raise MalformedExtractedFactError(
                "status=fact_extracted requires at least one 'fact_anchors' entry"
            )

        anchored = False
        if fact.requires_explicit_value:
            if polarity != POLARITY_AFFIRMATIVE:
                check_failures.append(CHECK_FAILURE_POLARITY_NOT_AFFIRMATIVE)
            if value is None or not canonicalize(value).strip():
                raise MalformedExtractedFactError(
                    "status=fact_extracted for a value question requires a non-empty 'value'"
                )
            if len(canonicalize(value)) > MAX_VALUE_LENGTH:
                raise MalformedExtractedFactError(
                    f"'value' exceeds the maximum length of {MAX_VALUE_LENGTH} characters"
                )
            if value_kind is None:
                raise MalformedExtractedFactError(
                    "status=fact_extracted for a value question requires 'value_kind'"
                )
            canon_value = canonicalize(value)
            anchored = any(
                canon_value in canonicalize(bundle.proofs[index].quote) for index in anchors
            )
            if not anchored:
                check_failures.append(CHECK_FAILURE_VALUE_NOT_ANCHORED)
        else:
            if value is not None:
                raise MalformedExtractedFactError(
                    "status=fact_extracted for an existence/boolean question requires 'value' "
                    "to be null"
                )
            if value_kind is not None:
                raise MalformedExtractedFactError(
                    "status=fact_extracted for an existence/boolean question requires "
                    "'value_kind' to be null"
                )
            anchored = True
        return ExtractedFactV1(
            status=status,
            subject=subject,
            attribute=attribute,
            value=value,
            value_kind=value_kind,
            polarity=polarity,
            fact_anchors=anchors,
            anchored=anchored,
            check_failures=check_failures,
            reason=reason,
        )

    if value is not None:
        raise MalformedExtractedFactError("status=no_fact requires 'value' to be null")
    if value_kind is not None:
        raise MalformedExtractedFactError("status=no_fact requires 'value_kind' to be null")
    if anchors:
        raise MalformedExtractedFactError("status=no_fact requires 'fact_anchors' to be empty")
    if polarity == POLARITY_AFFIRMATIVE:
        raise MalformedExtractedFactError("status=no_fact requires a non-affirmative polarity")
    return ExtractedFactV1(
        status=status,
        subject=subject,
        attribute=attribute,
        value=None,
        value_kind=None,
        polarity=polarity,
        fact_anchors=[],
        anchored=False,
        check_failures=[],
        reason=reason,
    )


def compose_attribute_binding_supported(
    proof: ProofDecisionV1,
    extracted: ExtractedFactV1 | None,
    fact: RequestedFactV1,
) -> bool:
    """Composed final supported decision (fail-closed).

    ``supported`` is true only when the proof is valid AND the extracted fact
    is present AND the deterministic conjuncts hold. A missing extracted fact
    (fail-closed path) is never supported.
    """
    if not proof.supported or extracted is None:
        return False
    if extracted.status != FACT_STATUS_EXTRACTED:
        return False
    if extracted.check_failures:
        return False
    if fact.requires_explicit_value:
        if extracted.polarity != POLARITY_AFFIRMATIVE:
            return False
        if extracted.value is None or not canonicalize(extracted.value).strip():
            return False
        return extracted.anchored
    return extracted.polarity in (POLARITY_AFFIRMATIVE, POLARITY_NEGATIVE)


def build_extracted_fact_payload(
    question: str,
    fact: RequestedFactV1,
    bundle: VerifiedProofBundleV1,
    sources: Mapping[str, str],
) -> dict[str, Any]:
    """Build the stage-3 extraction input SERVER-SIDE from verified proofs only.

    Identical isolation guarantee to RF1: the model sees the trusted question,
    the trusted requested fact, and for each VALID proof the exact quote plus
    the full canonicalized content of THAT cited source only. No sibling chunk
    text, no raw evidence bundle, no evaluation metadata can appear.
    """
    canonical = canonical_sources(sources)
    items: list[dict[str, Any]] = []
    for index, proof in enumerate(bundle.proofs):
        if proof.source_id not in canonical:
            raise UnknownProofSourceError(
                f"proof source_id {proof.source_id!r} is not present in the supplied evidence"
            )
        if canonical[proof.source_id].find(proof.quote) == -1:
            raise ExtractedFactAnchoringError(
                f"validated proof {proof.source_id!r} no longer matches its cited source"
            )
        items.append(
            {
                "index": index,
                "source_id": proof.source_id,
                "quote": proof.quote,
                "source_content": canonical[proof.source_id],
            }
        )
    return {
        "question": question,
        "requested_fact": _fact_payload(fact),
        "proofs": items,
    }


def _fact_payload(fact: RequestedFactV1) -> dict[str, Any]:
    from app.evaluation.verifier_requested_fact import requested_fact_to_dict

    return requested_fact_to_dict(fact)


def extracted_fact_to_dict(decision: ExtractedFactV1) -> dict[str, Any]:
    """Serialize an extracted fact (stable field order)."""
    return {
        "schema_version": EXTRACTED_FACT_SCHEMA_VERSION,
        "status": decision.status,
        "subject": decision.subject,
        "attribute": decision.attribute,
        "value": decision.value,
        "value_kind": decision.value_kind,
        "polarity": decision.polarity,
        "fact_anchors": list(decision.fact_anchors),
        "anchored": decision.anchored,
        "check_failures": list(decision.check_failures),
        "reason": decision.reason,
    }
