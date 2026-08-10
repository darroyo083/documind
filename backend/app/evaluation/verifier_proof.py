"""Server-side proof contract for the E1c verifiable-sufficiency spike.

Evaluation-only. Nothing in this module is imported by production code.

The E1c spike tests whether ``supported=true`` can require an explicit
evidence proof whose semantic sufficiency is checked independently. This
module implements the server-side (deterministic) half of that architecture
per ``worker_c_e1c_proof_contract.md``:

- P1 (one-pass control): the model returns ``{"supported": bool, "proofs":
  [{"source_id": str, "quote": str}]}`` and the server verifies that every
  quote is an EXACT substring of its cited source under minimal
  canonicalization. ``supported=true`` requires at least one valid proof.
- P2 (two-pass): pass 1 uses the same proof contract; pass 2 is an isolated
  sufficiency judge that receives ONLY the question plus the verified proofs
  (quote + full canonical content of THAT cited source only). Final
  ``supported = (proof valid AND judge decision == "entailed")``.

Canonicalization is deliberately minimal and lossless-for-match only:

    canon(s) = s.replace("\\r\\n", "\\n").replace("\\r", "\\n")

CRLF and lone CR both map to LF; LF is untouched. There is NO case folding,
NO whitespace collapsing, NO strip for matching, and NO Unicode NFC/NFD
normalization. A mis-cased or re-spaced quote must FAIL verification.

All checks in this module are pure set/substring/equality operations on the
supplied evidence payload: no fuzzy matching, no semantic rewriting, no I/O,
no model calls, no network.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

PROOF_SCHEMA_VERSION = "1"
MAX_QUOTE_LENGTH = 5000

PROOF_ALLOWED_KEYS = frozenset({"supported", "proofs"})
PROOF_CLAIM_ALLOWED_KEYS = frozenset({"source_id", "quote"})
JUDGE_ALLOWED_KEYS = frozenset({"decision", "supporting_proof_indexes", "reason"})

PROOF_STATUS_VALID = "valid"
PROOF_STATUS_QUOTE_NOT_FOUND = "quote_not_found"
PROOF_STATUS_EMPTY_QUOTE = "empty_quote"
PROOF_STATUS_UNKNOWN_SOURCE = "unknown_source"
PROOF_STATUS_DUPLICATE_DROPPED = "duplicate_dropped"

VALID_PROOF_STATUSES = frozenset(
    {
        PROOF_STATUS_VALID,
        PROOF_STATUS_QUOTE_NOT_FOUND,
        PROOF_STATUS_EMPTY_QUOTE,
        PROOF_STATUS_UNKNOWN_SOURCE,
        PROOF_STATUS_DUPLICATE_DROPPED,
    }
)

JUDGE_DECISION_ENTAILED = "entailed"
JUDGE_DECISION_INSUFFICIENT = "insufficient"
JUDGE_DECISION_CONTRADICTED = "contradicted"

VALID_JUDGE_DECISIONS = frozenset(
    {
        JUDGE_DECISION_ENTAILED,
        JUDGE_DECISION_INSUFFICIENT,
        JUDGE_DECISION_CONTRADICTED,
    }
)


class ProofOutputError(ValueError):
    """Base class for controlled proof-contract output errors."""


class MalformedProofOutputError(ProofOutputError):
    """Output violates the proof decision schema (bad keys, wrong types)."""


class UnknownProofSourceError(ProofOutputError):
    """A proof cites a source id not present in the supplied evidence."""


class QuoteNotFoundError(ProofOutputError):
    """A verified proof's quote can no longer be located in its cited source.

    Raised only by invariant re-verification paths (e.g. building the pass-2
    judge payload from an already-validated bundle); a validated proof that
    no longer matches its source indicates a logic bug, never a model choice.
    """


class MissingValidProofError(ProofOutputError):
    """supported=true was returned but no proof survives server validation.

    Carries the per-proof validation results (``invalid_proofs``) so the
    measured failure categories (``quote_not_found``, ``empty_quote``,
    ``duplicate_dropped``) remain observable on the hard-fail path.
    """

    def __init__(
        self,
        message: str,
        invalid_proofs: Sequence[ProofValidationResultV1] = (),
    ):
        super().__init__(message)
        self.invalid_proofs = list(invalid_proofs)


@dataclass(frozen=True)
class ProofClaimV1:
    """Model-supplied untrusted claim: one (source_id, quote) pair."""

    source_id: str
    quote: str


@dataclass(frozen=True)
class ProofValidationResultV1:
    """Per-proof server status for one submitted claim.

    ``status`` is one of the :data:`VALID_PROOF_STATUSES` values. Results are
    measurements: invalid proofs are recorded here and dropped, never
    repaired and never retried.
    """

    source_id: str
    quote: str
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class EvidenceProofV1:
    """Server-validated proof with server-computed code-point offsets.

    ``quote`` is the canonicalized quote (CRLF/CR normalized to LF); offsets
    are the first-occurrence code-point offsets into the canonicalized source
    content. ``status`` is always :data:`PROOF_STATUS_VALID`.
    """

    source_id: str
    quote: str
    start_offset: int
    end_offset: int
    status: str = PROOF_STATUS_VALID


@dataclass(frozen=True)
class VerifiedProofBundleV1:
    """Ordered, deduplicated, validated proof set (the only input to stage 2)."""

    proofs: list[EvidenceProofV1] = field(default_factory=list)


@dataclass(frozen=True)
class ProofDecisionV1:
    """Stage-1 decision after server-side proof validation."""

    supported: bool
    proofs: list[EvidenceProofV1] = field(default_factory=list)
    invalid_proofs: list[ProofValidationResultV1] = field(default_factory=list)


@dataclass(frozen=True)
class SufficiencyDecisionV1:
    """Stage-2 judge output (pass-2 contract, server-validated).

    ``decision`` is one of :data:`VALID_JUDGE_DECISIONS`;
    ``supporting_proof_indexes`` indexes the judge's input proof list;
    ``reason`` is free text used only for audit, never for the decision.
    """

    decision: str
    supporting_proof_indexes: list[int]
    reason: str = ""


@dataclass(frozen=True)
class EntailmentDecisionV1:
    """Composed final decision: stage-1 proof bundle + stage-2 sufficiency.

    ``sufficiency`` is ``None`` when pass 2 never ran (fail-closed path:
    empty/invalid pass-1 proof means ``supported=false`` by construction).
    """

    proof: ProofDecisionV1
    sufficiency: SufficiencyDecisionV1 | None = None


def canonicalize(text: str) -> str:
    """Minimal lossless-for-match normalization: CRLF/CR -> LF, nothing else."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def find_first_occurrence(content: str, quote: str) -> tuple[int, int] | None:
    """First-occurrence code-point offsets of ``quote`` in ``content``.

    Returns ``(start_offset, end_offset)`` or ``None`` when the quote is not
    present. Offsets are Python string (code-point) indexes into
    ``content``, which must already be canonicalized.
    """
    index = content.find(quote)
    if index == -1:
        return None
    return index, index + len(quote)


def canonical_sources(sources: Mapping[str, str]) -> dict[str, str]:
    """Map source_id -> canonicalized content for the supplied evidence."""
    return {source_id: canonicalize(content) for source_id, content in sources.items()}


def parse_proof_claims(raw: dict[str, Any]) -> list[ProofClaimV1]:
    """Parse the model's untrusted ``proofs`` list into typed claims.

    Schema violations are fatal: the top-level shape of every proof entry
    (exactly ``{"source_id": str, "quote": str}``) is part of the proof
    contract, so malformed entries raise :class:`MalformedProofOutputError`
    rather than being measured per-proof.
    """
    proofs = raw.get("proofs")
    if proofs is None:
        return []
    if not isinstance(proofs, list):
        raise MalformedProofOutputError("'proofs' must be a list")
    claims: list[ProofClaimV1] = []
    for index, entry in enumerate(proofs):
        if not isinstance(entry, dict):
            raise MalformedProofOutputError(f"proofs[{index}] must be an object")
        unknown = sorted(set(entry) - PROOF_CLAIM_ALLOWED_KEYS)
        if unknown:
            raise MalformedProofOutputError(f"proofs[{index}] has unknown field(s): {unknown}")
        source_id = entry.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise MalformedProofOutputError(f"proofs[{index}].source_id must be a non-empty string")
        quote = entry.get("quote")
        if not isinstance(quote, str):
            raise MalformedProofOutputError(f"proofs[{index}].quote must be a string")
        claims.append(ProofClaimV1(source_id=source_id, quote=quote))
    return claims


def _proof_status(
    claim: ProofClaimV1,
    canonical: str,
    max_quote_length: int,
    seen: set[tuple[str, str]],
) -> ProofValidationResultV1 | None:
    """Classify one claim. Returns None for a VALID proof, else the failure.

    Raises :class:`UnknownProofSourceError` immediately for unknown source
    ids (mirrors the v2 ``UnknownEvidenceSourceError`` hard-fail pattern).
    """
    canonical_quote = canonicalize(claim.quote)
    if not canonical_quote.strip():
        return ProofValidationResultV1(
            source_id=claim.source_id,
            quote=canonical_quote,
            status=PROOF_STATUS_EMPTY_QUOTE,
            reason="quote is empty or whitespace-only after canonicalization",
        )
    if len(canonical_quote) > max_quote_length:
        return ProofValidationResultV1(
            source_id=claim.source_id,
            quote=canonical_quote,
            status=PROOF_STATUS_EMPTY_QUOTE,
            reason=f"quote exceeds the maximum length of {max_quote_length} characters",
        )
    if canonical.find(canonical_quote) == -1:
        return ProofValidationResultV1(
            source_id=claim.source_id,
            quote=canonical_quote,
            status=PROOF_STATUS_QUOTE_NOT_FOUND,
            reason="canonical quote is not an exact substring of the cited source",
        )
    key = (claim.source_id, canonical_quote)
    if key in seen:
        return ProofValidationResultV1(
            source_id=claim.source_id,
            quote=canonical_quote,
            status=PROOF_STATUS_DUPLICATE_DROPPED,
            reason="duplicate (source_id, canonical_quote); first occurrence wins",
        )
    seen.add(key)
    return None


def validate_proof_decision(
    raw: dict[str, Any],
    sources: Mapping[str, str],
    *,
    max_quote_length: int = MAX_QUOTE_LENGTH,
) -> ProofDecisionV1:
    """Strictly validate a parsed proof-contract output.

    ``sources`` maps every supplied evidence ``source_id`` to its raw
    content; canonicalization is applied server-side to both sides. Rules
    enforced here (never silently accepting invalid output):

    - ``raw`` must be a JSON object with a boolean ``supported``; the only
      allowed keys are ``{"supported", "proofs"}``.
    - ``supported=false`` requires ``proofs`` empty or absent.
    - ``supported=true`` requires at least one submitted proof.
    - Every proof's ``source_id`` must exist in ``sources``
      (:class:`UnknownProofSourceError`, hard fail).
    - Per-proof failure categories are MEASURED and recorded in
      ``invalid_proofs``: ``empty_quote`` (blank/whitespace-only or over the
      length cap), ``quote_not_found`` (canonical quote not an exact
      substring of the cited canonical source content), and
      ``duplicate_dropped`` (first occurrence of a ``(source_id,
      canonical_quote)`` wins).
    - Valid proofs carry server-computed first-occurrence code-point offsets.
    - ``supported=true`` survives only with at least one valid proof;
      otherwise the whole output is rejected with
      :class:`MissingValidProofError` (an invalid output, recorded, and it
      can never become ``supported``).
    - Deterministic: same input bytes, same output bytes.

    Raises:
        MalformedProofOutputError: schema violation.
        UnknownProofSourceError: a proof cites a source id not supplied.
        MissingValidProofError: supported=true with zero valid proofs.
    """
    if not isinstance(raw, dict):
        raise MalformedProofOutputError("proof output must be a JSON object")
    unknown = sorted(set(raw) - PROOF_ALLOWED_KEYS)
    if unknown:
        raise MalformedProofOutputError(f"proof output has unknown field(s): {unknown}")
    if "supported" not in raw:
        raise MalformedProofOutputError("proof output is missing 'supported'")
    if not isinstance(raw["supported"], bool):
        raise MalformedProofOutputError("'supported' must be a boolean")

    claims = parse_proof_claims(raw)
    if not raw["supported"]:
        if claims:
            raise MalformedProofOutputError("supported=false requires proofs to be empty or absent")
        return ProofDecisionV1(supported=False)
    if not claims:
        raise MissingValidProofError(
            "supported=true requires at least one proof (source_id + quote)"
        )

    canonical = canonical_sources(sources)
    seen: set[tuple[str, str]] = set()
    valid_proofs: list[EvidenceProofV1] = []
    invalid_proofs: list[ProofValidationResultV1] = []
    for claim in claims:
        if claim.source_id not in canonical:
            raise UnknownProofSourceError(
                f"proof source_id {claim.source_id!r} is not present in the supplied evidence"
            )
        failure = _proof_status(claim, canonical[claim.source_id], max_quote_length, seen)
        if failure is not None:
            invalid_proofs.append(failure)
            continue
        offsets = find_first_occurrence(canonical[claim.source_id], canonicalize(claim.quote))
        assert offsets is not None
        start_offset, end_offset = offsets
        valid_proofs.append(
            EvidenceProofV1(
                source_id=claim.source_id,
                quote=canonicalize(claim.quote),
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )

    if not valid_proofs:
        raise MissingValidProofError(
            "supported=true requires at least one valid proof after server validation; "
            f"all {len(claims)} submitted proof(s) failed validation",
            invalid_proofs=invalid_proofs,
        )
    return ProofDecisionV1(supported=True, proofs=valid_proofs, invalid_proofs=invalid_proofs)


def build_verified_bundle(decision: ProofDecisionV1) -> VerifiedProofBundleV1:
    """Extract the ordered, deduplicated, server-validated proof set."""
    return VerifiedProofBundleV1(proofs=list(decision.proofs))


def build_judge_payload(
    question: str,
    bundle: VerifiedProofBundleV1,
    sources: Mapping[str, str],
) -> dict[str, Any]:
    """Build the pass-2 judge input SERVER-SIDE from verified proofs only.

    The judge sees the trusted question plus, for each VALID proof, the
    exact quote and the full canonicalized content of THAT cited source
    only. No sibling chunk text, no raw evidence bundle, no evaluation
    metadata can appear in the payload by construction. Each proof's quote
    is re-verified against its source (an invariant guard; a validated proof
    must still match).
    """
    canonical = canonical_sources(sources)
    items: list[dict[str, Any]] = []
    for index, proof in enumerate(bundle.proofs):
        if proof.source_id not in canonical:
            raise UnknownProofSourceError(
                f"proof source_id {proof.source_id!r} is not present in the supplied evidence"
            )
        if canonical[proof.source_id].find(proof.quote) == -1:
            raise QuoteNotFoundError(
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
    return {"question": question, "proofs": items}


def validate_sufficiency_decision(
    raw: dict[str, Any],
    proof_count: int,
) -> SufficiencyDecisionV1:
    """Strictly validate a parsed pass-2 judge output.

    Contract: ``{"decision": entailed|insufficient|contradicted,
    "supporting_proof_indexes": [int], "reason": str}``. Unknown keys are
    rejected. ``entailed`` requires at least one supporting index;
    ``insufficient``/``contradicted`` require an empty list. Indexes are
    deduplicated first-occurrence and must be in range for the judge's input
    proof list. ``reason`` is audit-only free text.
    """
    if not isinstance(raw, dict):
        raise MalformedProofOutputError("judge output must be a JSON object")
    unknown = sorted(set(raw) - JUDGE_ALLOWED_KEYS)
    if unknown:
        raise MalformedProofOutputError(f"judge output has unknown field(s): {unknown}")
    if "decision" not in raw:
        raise MalformedProofOutputError("judge output is missing 'decision'")
    decision = raw["decision"]
    if decision not in VALID_JUDGE_DECISIONS:
        raise MalformedProofOutputError(
            f"'decision' must be one of {sorted(VALID_JUDGE_DECISIONS)}; got {decision!r}"
        )
    if "supporting_proof_indexes" not in raw:
        raise MalformedProofOutputError("judge output is missing 'supporting_proof_indexes'")
    indexes = raw["supporting_proof_indexes"]
    if not isinstance(indexes, list):
        raise MalformedProofOutputError("'supporting_proof_indexes' must be a list")
    normalized: list[int] = []
    for index in indexes:
        if not isinstance(index, int) or isinstance(index, bool):
            raise MalformedProofOutputError("'supporting_proof_indexes' entries must be integers")
        if index < 0 or index >= proof_count:
            raise MalformedProofOutputError(
                f"supporting proof index {index} is out of range for {proof_count} proof(s)"
            )
        if index not in normalized:
            normalized.append(index)

    if decision == JUDGE_DECISION_ENTAILED and not normalized:
        raise MalformedProofOutputError(
            "decision=entailed requires at least one supporting_proof_index"
        )
    if decision != JUDGE_DECISION_ENTAILED and normalized:
        raise MalformedProofOutputError(
            f"decision={decision} requires supporting_proof_indexes to be empty"
        )
    reason = raw.get("reason")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise MalformedProofOutputError("'reason' must be a string")
    return SufficiencyDecisionV1(
        decision=decision,
        supporting_proof_indexes=normalized,
        reason=reason,
    )


def compose_supported(
    proof: ProofDecisionV1,
    sufficiency: SufficiencyDecisionV1 | None,
) -> bool:
    """Composed final supported decision.

    P1: ``supported`` is exactly the stage-1 decision (which is already
    guaranteed to carry at least one valid proof). P2: ``supported`` is true
    only when the stage-1 proof is valid AND the judge decided ``entailed``;
    a missing judge decision (fail-closed path) is never supported.
    """
    if not proof.supported:
        return False
    if sufficiency is None:
        return False
    return sufficiency.decision == JUDGE_DECISION_ENTAILED
