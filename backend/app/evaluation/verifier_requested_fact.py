"""Server-side RequestedFact (RF1) contract for the E1d requested-fact spike.

Evaluation-only. Nothing in this module is imported by production code.

The RF1 architecture makes the semantic target of a TRUSTED question explicit
BEFORE asking whether evidence supports it, per ``worker_a_requested_fact_contract.md``
and ``worker_b_answerability_contract.md``:

- Stage 1 derives a :class:`RequestedFactV1` from the trusted question ONLY.
  Document evidence can never influence its generation (architectural
  isolation); the server validates the derivation deterministically.
- Stage 2 reuses the proof contract from ``verifier_proof.py`` unchanged
  (exact-substring provenance).
- Stage 3 produces an :class:`AnswerabilityDecisionV1`: the model supplies an
  EXPLICIT extracted answer and the server checks, deterministically, whether
  that answer is anchored in a server-verified proof quote and consistent with
  the kind of fact the question requests.

The value-vs-existence distinction is the load-bearing axis:

- Path V (``requires_explicit_value=true``): supported requires an explicit
  extracted value whose canonicalized text is an EXACT substring of a verified
  proof quote (literal containment, no case folding, no fuzzy matching). An
  absence statement can never supply a value -> ``insufficient`` -> NOT
  supported.
- Path B (``requires_explicit_value=false``): supported requires an explicit
  yes/no answer in the controlled vocabulary ``{"yes", "no"}`` plus at least
  one anchor (the polarity quote). An absence statement directly answers an
  existence question -> ``answered``, ``answer="no"``, supported.

All checks in this module are pure schema/enum/substring operations on the
supplied payloads: no fuzzy matching, no semantic rewriting, no I/O, no model
calls, no network. Same input bytes, same output bytes.
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

REQUESTED_FACT_SCHEMA_VERSION = "requested_fact_v1"
MAX_REQUESTED_FACT_FIELD_LENGTH = 500

QUESTION_KIND_VALUE = "value"
QUESTION_KIND_EXISTENCE = "existence"
QUESTION_KIND_BOOLEAN = "boolean"
QUESTION_KINDS = frozenset({QUESTION_KIND_VALUE, QUESTION_KIND_EXISTENCE, QUESTION_KIND_BOOLEAN})

EXPECTED_ANSWER_KIND_NUMERIC = "numeric"
EXPECTED_ANSWER_KIND_DATE_OR_TIME = "date_or_time"
EXPECTED_ANSWER_KIND_ENTITY = "entity"
EXPECTED_ANSWER_KIND_TEXT = "text"
EXPECTED_ANSWER_KIND_BOOLEAN = "boolean"
EXPECTED_ANSWER_KIND_LIST = "list"
EXPECTED_ANSWER_KINDS = frozenset(
    {
        EXPECTED_ANSWER_KIND_NUMERIC,
        EXPECTED_ANSWER_KIND_DATE_OR_TIME,
        EXPECTED_ANSWER_KIND_ENTITY,
        EXPECTED_ANSWER_KIND_TEXT,
        EXPECTED_ANSWER_KIND_BOOLEAN,
        EXPECTED_ANSWER_KIND_LIST,
    }
)
VALUE_ANSWER_KINDS = frozenset(
    {
        EXPECTED_ANSWER_KIND_NUMERIC,
        EXPECTED_ANSWER_KIND_DATE_OR_TIME,
        EXPECTED_ANSWER_KIND_ENTITY,
        EXPECTED_ANSWER_KIND_TEXT,
        EXPECTED_ANSWER_KIND_LIST,
    }
)

POLARITY_AFFIRMATIVE = "affirmative"
POLARITY_NEGATIVE = "negative"
POLARITIES = frozenset({POLARITY_AFFIRMATIVE, POLARITY_NEGATIVE})

REQUESTED_FACT_ALLOWED_KEYS = frozenset(
    {
        "schema_version",
        "question_kind",
        "expected_answer_kind",
        "requires_explicit_value",
        "subject",
        "requested_attribute",
        "proposition",
        "polarity",
    }
)

ANSWERABILITY_SCHEMA_VERSION = "1"
MAX_ANSWER_LENGTH = 2000

ANSWER_STATUS_ANSWERED = "answered"
ANSWER_STATUS_INSUFFICIENT = "insufficient"
ANSWER_STATUS_CONTRADICTED = "contradicted"  # server-derived only, never model-emittable

VALID_ANSWER_STATUSES = frozenset({ANSWER_STATUS_ANSWERED, ANSWER_STATUS_INSUFFICIENT})

ANSWER_KIND_VALUE = "value"
ANSWER_KIND_BOOLEAN = "boolean"
ANSWER_KIND_EXISTENCE = "existence"
ANSWER_KIND_DATE_OR_TIME = "date_or_time"
ANSWER_KIND_ENTITY = "entity"
ANSWER_KIND_TEXT = "text"
ANSWER_KIND_LIST = "list"
ANSWER_KINDS = frozenset(
    {
        ANSWER_KIND_VALUE,
        ANSWER_KIND_BOOLEAN,
        ANSWER_KIND_EXISTENCE,
        ANSWER_KIND_DATE_OR_TIME,
        ANSWER_KIND_ENTITY,
        ANSWER_KIND_TEXT,
        ANSWER_KIND_LIST,
    }
)

CONTROLLED_BOOLEAN_ANSWERS = frozenset({"yes", "no"})

ANSWER_ALLOWED_KEYS = frozenset({"status", "answer", "answer_kind", "answer_anchors", "reason"})

CHECK_FAILURE_ANSWER_NOT_ANCHORED = "answer_not_anchored"
CHECK_FAILURE_ANSWER_KIND_MISMATCH = "answer_kind_mismatch"

# Kind-consistency matrix (Worker B section 5): the model's answer_kind must
# match the question kind of the RequestedFactV1. value questions (any
# expected_answer_kind) require answer_kind=value; boolean/existence questions
# require answer_kind=boolean/existence respectively.
ANSWER_KIND_MATRIX = {
    QUESTION_KIND_VALUE: ANSWER_KIND_VALUE,
    QUESTION_KIND_EXISTENCE: ANSWER_KIND_EXISTENCE,
    QUESTION_KIND_BOOLEAN: ANSWER_KIND_BOOLEAN,
}


class RequestedFactOutputError(ValueError):
    """Base class for controlled requested-fact output errors."""


class MalformedRequestedFactError(RequestedFactOutputError):
    """Output violates the RequestedFactV1 schema (bad keys, wrong types, bad enums)."""


class AnswerabilityOutputError(ValueError):
    """Base class for controlled answerability output errors."""


class MalformedAnswerabilityOutputError(AnswerabilityOutputError):
    """Output violates the AnswerabilityDecisionV1 schema (bad keys, wrong types)."""


class AnswerAnchoringError(AnswerabilityOutputError):
    """Answer-anchoring invariant violated on a server-owned path.

    Raised only by invariant re-verification paths (e.g. building the stage-3
    answerability payload from an already-validated bundle): a validated proof
    that no longer matches its source indicates a logic bug, never a model
    choice (mirrors ``QuoteNotFoundError`` in ``verifier_proof.py``).
    """


@dataclass(frozen=True)
class RequestedFactV1:
    """The semantic target of a TRUSTED question, derived from question text only.

    ``question_kind`` distinguishes value requests (``value``) from
    existence/boolean determinations (``existence``/``boolean``);
    ``requires_explicit_value`` is the value-vs-existence switch the
    answerability stage routes on. ``proposition`` is the neutral statement of
    what the question asks; ``polarity`` fixes the yes/no mapping for
    boolean/existence questions. All fields are model-derived and
    schema-validated only; no server check can prove they match the question's
    semantics.
    """

    question_kind: str
    expected_answer_kind: str
    requires_explicit_value: bool
    subject: str
    requested_attribute: str
    proposition: str
    polarity: str


@dataclass(frozen=True)
class AnswerabilityDecisionV1:
    """Composed stage-3 decision: the answerability half of the verifier.

    ``status`` is ``answered`` only when every server check passed;
    ``insufficient`` when the model abstained and the abstention is
    consistent; ``contradicted`` when the model claimed an answer the verified
    evidence cannot support (derived server-side, measured, never repaired).
    ``anchored``/``kind_consistent`` are per-check measurements; for an
    abstention both are False and ``check_failures`` stays empty.
    """

    status: str
    answer: str | None
    answer_kind: str | None
    answer_anchors: list[int]
    anchored: bool
    kind_consistent: bool
    check_failures: list[str]
    reason: str = ""


@dataclass(frozen=True)
class RequestedFactDecisionV1:
    """Composed final RF1 decision: requested fact + proof + answerability.

    ``answerability`` is ``None`` when stage 3 never ran (fail-closed path:
    malformed stage 1 or empty/invalid stage 2 proof means ``supported=false``
    by construction).
    """

    fact: RequestedFactV1
    proof: ProofDecisionV1
    answerability: AnswerabilityDecisionV1 | None = None
    supported: bool = False


def validate_requested_fact_output(raw: dict[str, Any]) -> RequestedFactV1:
    """Strictly validate a parsed requested-fact output.

    Rules enforced here (never silently repairing invalid output):

    - ``raw`` must be a JSON object whose keys are exactly
      :data:`REQUESTED_FACT_ALLOWED_KEYS`; any extra key is rejected.
    - ``schema_version`` must equal :data:`REQUESTED_FACT_SCHEMA_VERSION`.
    - ``question_kind``/``expected_answer_kind``/``polarity`` must be in the
      controlled enums; ``requires_explicit_value`` must be a ``bool``.
    - Cross-field consistency (the deterministic core): ``question_kind=value``
      requires ``expected_answer_kind`` in :data:`VALUE_ANSWER_KINDS`,
      ``requires_explicit_value=true`` and ``polarity=affirmative``;
      ``question_kind`` in ``{existence, boolean}`` requires
      ``expected_answer_kind=boolean`` and ``requires_explicit_value=false``.
    - ``subject``/``requested_attribute``/``proposition`` are non-empty strings
      of at most :data:`MAX_REQUESTED_FACT_FIELD_LENGTH` characters.
    - Deterministic: same input bytes, same output bytes.

    Raises:
        MalformedRequestedFactError: any schema, enum, or cross-field violation.
    """
    if not isinstance(raw, dict):
        raise MalformedRequestedFactError("requested-fact output must be a JSON object")
    unknown = sorted(set(raw) - REQUESTED_FACT_ALLOWED_KEYS)
    if unknown:
        raise MalformedRequestedFactError(f"requested-fact output has unknown field(s): {unknown}")
    if raw.get("schema_version") != REQUESTED_FACT_SCHEMA_VERSION:
        raise MalformedRequestedFactError(
            f"'schema_version' must be {REQUESTED_FACT_SCHEMA_VERSION!r}"
        )

    question_kind = raw.get("question_kind")
    if question_kind not in QUESTION_KINDS:
        raise MalformedRequestedFactError(
            f"'question_kind' must be one of {sorted(QUESTION_KINDS)}; got {question_kind!r}"
        )
    expected_answer_kind = raw.get("expected_answer_kind")
    if expected_answer_kind not in EXPECTED_ANSWER_KINDS:
        raise MalformedRequestedFactError(
            f"'expected_answer_kind' must be one of {sorted(EXPECTED_ANSWER_KINDS)}; "
            f"got {expected_answer_kind!r}"
        )
    requires_explicit_value = raw.get("requires_explicit_value")
    if not isinstance(requires_explicit_value, bool):
        raise MalformedRequestedFactError("'requires_explicit_value' must be a boolean")
    polarity = raw.get("polarity")
    if polarity not in POLARITIES:
        raise MalformedRequestedFactError(
            f"'polarity' must be one of {sorted(POLARITIES)}; got {polarity!r}"
        )
    for key in ("subject", "requested_attribute", "proposition"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise MalformedRequestedFactError(f"'{key}' must be a non-empty string")
        if len(value) > MAX_REQUESTED_FACT_FIELD_LENGTH:
            raise MalformedRequestedFactError(
                f"'{key}' exceeds the maximum length of "
                f"{MAX_REQUESTED_FACT_FIELD_LENGTH} characters"
            )

    if question_kind == QUESTION_KIND_VALUE:
        if expected_answer_kind not in VALUE_ANSWER_KINDS:
            raise MalformedRequestedFactError(
                f"question_kind=value requires expected_answer_kind in {sorted(VALUE_ANSWER_KINDS)}"
            )
        if not requires_explicit_value:
            raise MalformedRequestedFactError(
                "question_kind=value requires requires_explicit_value=true"
            )
        if polarity != POLARITY_AFFIRMATIVE:
            raise MalformedRequestedFactError("question_kind=value requires polarity=affirmative")
    else:
        if expected_answer_kind != EXPECTED_ANSWER_KIND_BOOLEAN:
            raise MalformedRequestedFactError(
                f"question_kind={question_kind} requires "
                f"expected_answer_kind={EXPECTED_ANSWER_KIND_BOOLEAN}"
            )
        if requires_explicit_value:
            raise MalformedRequestedFactError(
                f"question_kind={question_kind} requires requires_explicit_value=false"
            )

    return RequestedFactV1(
        question_kind=question_kind,
        expected_answer_kind=expected_answer_kind,
        requires_explicit_value=requires_explicit_value,
        subject=raw["subject"],
        requested_attribute=raw["requested_attribute"],
        proposition=raw["proposition"],
        polarity=polarity,
    )


def validate_answerability_decision(
    raw: dict[str, Any],
    bundle: VerifiedProofBundleV1,
    fact: RequestedFactV1,
) -> AnswerabilityDecisionV1:
    """Strictly validate a parsed stage-3 answerability output.

    Contract: ``{"status": answered|insufficient, "answer": str|null,
    "answer_kind": str|null, "answer_anchors": [int], "reason": str}``.
    ``contradicted`` is NOT model-emittable: it is derived server-side when the
    model claimed ``answered`` and any deterministic check failed.

    Rules:

    - Unknown keys rejected; ``status`` must be in :data:`VALID_ANSWER_STATUSES`.
    - Consistency (hard schema rules): ``status=answered`` requires a non-empty
      ``answer`` (not whitespace-only after canonicalization), a present
      ``answer_kind`` and at least one ``answer_anchors`` entry;
      ``status=insufficient`` requires ``answer=null``, ``answer_kind=null``
      and ``answer_anchors=[]``.
    - ``answer_anchors`` entries are integers (not bools), deduplicated
      first-occurrence, and in range for the verified bundle.
    - ``len(canonicalize(answer)) <= MAX_ANSWER_LENGTH``; ``answer_kind`` (when
      present) must be in :data:`ANSWER_KINDS`.
    - Kind consistency vs the :data:`ANSWER_KIND_MATRIX`: a mismatch is a
      measured check failure (``answer_kind_mismatch``), never repaired.
    - Anchoring per path: Path V (``requires_explicit_value=true``) requires
      literal containment ``canonicalize(answer) in canonicalize(quote)`` for at
      least one anchor, computed with ``verifier_proof.canonicalize`` (CRLF/CR
      -> LF only; NO case folding, NO whitespace collapsing, NO fuzzy matching).
      Path B (``requires_explicit_value=false``) requires ``answer`` in
      :data:`CONTROLLED_BOOLEAN_ANSWERS` plus at least one anchor. Failure is a
      measured ``answer_not_anchored`` check failure.
    - Status derivation: model ``answered`` with any check failure becomes
      ``contradicted`` (server-derived measurement, never repaired, never
      retried); a consistent abstention stays ``insufficient``.

    Raises:
        MalformedAnswerabilityOutputError: schema violation.
    """
    if not isinstance(raw, dict):
        raise MalformedAnswerabilityOutputError("answerability output must be a JSON object")
    unknown = sorted(set(raw) - ANSWER_ALLOWED_KEYS)
    if unknown:
        raise MalformedAnswerabilityOutputError(
            f"answerability output has unknown field(s): {unknown}"
        )
    status = raw.get("status")
    if status not in VALID_ANSWER_STATUSES:
        raise MalformedAnswerabilityOutputError(
            f"'status' must be one of {sorted(VALID_ANSWER_STATUSES)}; got {status!r}"
        )

    answer = raw.get("answer")
    if answer is not None and not isinstance(answer, str):
        raise MalformedAnswerabilityOutputError("'answer' must be a string or null")
    answer_kind = raw.get("answer_kind")
    if answer_kind is not None and not isinstance(answer_kind, str):
        raise MalformedAnswerabilityOutputError("'answer_kind' must be a string or null")
    anchors_raw = raw.get("answer_anchors")
    if not isinstance(anchors_raw, list):
        raise MalformedAnswerabilityOutputError("'answer_anchors' must be a list")

    if status == ANSWER_STATUS_ANSWERED:
        if answer is None or not canonicalize(answer).strip():
            raise MalformedAnswerabilityOutputError("status=answered requires a non-empty 'answer'")
        if answer_kind is None:
            raise MalformedAnswerabilityOutputError("status=answered requires 'answer_kind'")
        if not anchors_raw:
            raise MalformedAnswerabilityOutputError(
                "status=answered requires at least one 'answer_anchors' entry"
            )
    else:
        if answer is not None:
            raise MalformedAnswerabilityOutputError(
                "status=insufficient requires 'answer' to be null"
            )
        if answer_kind is not None:
            raise MalformedAnswerabilityOutputError(
                "status=insufficient requires 'answer_kind' to be null"
            )
        if anchors_raw:
            raise MalformedAnswerabilityOutputError(
                "status=insufficient requires 'answer_anchors' to be empty"
            )

    anchors: list[int] = []
    for index in anchors_raw:
        if not isinstance(index, int) or isinstance(index, bool):
            raise MalformedAnswerabilityOutputError("'answer_anchors' entries must be integers")
        if index < 0 or index >= len(bundle.proofs):
            raise MalformedAnswerabilityOutputError(
                f"answer anchor index {index} is out of range for {len(bundle.proofs)} proof(s)"
            )
        if index not in anchors:
            anchors.append(index)

    if answer is not None and len(canonicalize(answer)) > MAX_ANSWER_LENGTH:
        raise MalformedAnswerabilityOutputError(
            f"'answer' exceeds the maximum length of {MAX_ANSWER_LENGTH} characters"
        )
    if answer_kind is not None and answer_kind not in ANSWER_KINDS:
        raise MalformedAnswerabilityOutputError(
            f"'answer_kind' must be one of {sorted(ANSWER_KINDS)}; got {answer_kind!r}"
        )

    check_failures: list[str] = []
    anchored = False
    kind_consistent = False
    if status == ANSWER_STATUS_ANSWERED:
        if answer_kind == ANSWER_KIND_MATRIX[fact.question_kind]:
            kind_consistent = True
        else:
            check_failures.append(CHECK_FAILURE_ANSWER_KIND_MISMATCH)
        if fact.requires_explicit_value:
            assert answer is not None  # schema: answered requires a non-empty answer
            canon_answer = canonicalize(answer)
            anchored = any(
                canon_answer in canonicalize(bundle.proofs[index].quote) for index in anchors
            )
        else:
            anchored = answer in CONTROLLED_BOOLEAN_ANSWERS
        if not anchored:
            check_failures.append(CHECK_FAILURE_ANSWER_NOT_ANCHORED)
        if check_failures:
            status = ANSWER_STATUS_CONTRADICTED

    reason = raw.get("reason")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise MalformedAnswerabilityOutputError("'reason' must be a string")

    return AnswerabilityDecisionV1(
        status=status,
        answer=answer,
        answer_kind=answer_kind,
        answer_anchors=anchors,
        anchored=anchored,
        kind_consistent=kind_consistent,
        check_failures=check_failures,
        reason=reason,
    )


def compose_requested_fact_supported(
    proof: ProofDecisionV1,
    answerability: AnswerabilityDecisionV1 | None,
) -> bool:
    """Composed final supported decision.

    ``supported`` is true only when every deterministic conjunct holds:
    stage-1 proof valid AND stage-3 status ``answered`` AND a non-empty answer
    AND the answer anchored AND the answer kind consistent. A missing
    answerability decision (fail-closed path) is never supported. There is NO
    path from "model said answered" to supported without every conjunct
    holding.
    """
    if not proof.supported or answerability is None:
        return False
    if answerability.status != ANSWER_STATUS_ANSWERED:
        return False
    if answerability.answer is None or not canonicalize(answerability.answer).strip():
        return False
    if not answerability.anchored or not answerability.kind_consistent:
        return False
    return True


def build_answerability_payload(
    question: str,
    fact: RequestedFactV1,
    bundle: VerifiedProofBundleV1,
    sources: Mapping[str, str],
) -> dict[str, Any]:
    """Build the stage-3 answerability input SERVER-SIDE from verified proofs only.

    The model sees the trusted question, the trusted requested fact, and, for
    each VALID proof, the exact quote and the full canonicalized content of
    THAT cited source only. No sibling chunk text, no raw evidence bundle, and
    no evaluation metadata can appear in the payload by construction. Each
    proof's quote is re-verified against its source (an invariant guard; a
    validated proof must still match) - failure raises
    :class:`AnswerAnchoringError` (the RF1-owned invariant error).
    """
    canonical = canonical_sources(sources)
    items: list[dict[str, Any]] = []
    for index, proof in enumerate(bundle.proofs):
        if proof.source_id not in canonical:
            raise UnknownProofSourceError(
                f"proof source_id {proof.source_id!r} is not present in the supplied evidence"
            )
        if canonical[proof.source_id].find(proof.quote) == -1:
            raise AnswerAnchoringError(
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
        "requested_fact": requested_fact_to_dict(fact),
        "proofs": items,
    }


def requested_fact_to_dict(fact: RequestedFactV1) -> dict[str, Any]:
    """Serialize a requested fact (stable field order for byte-determinism)."""
    return {
        "schema_version": REQUESTED_FACT_SCHEMA_VERSION,
        "question_kind": fact.question_kind,
        "expected_answer_kind": fact.expected_answer_kind,
        "requires_explicit_value": fact.requires_explicit_value,
        "subject": fact.subject,
        "requested_attribute": fact.requested_attribute,
        "proposition": fact.proposition,
        "polarity": fact.polarity,
    }


def answerability_to_dict(decision: AnswerabilityDecisionV1) -> dict[str, Any]:
    """Serialize an answerability decision (stable field order)."""
    return {
        "schema_version": ANSWERABILITY_SCHEMA_VERSION,
        "status": decision.status,
        "answer": decision.answer,
        "answer_kind": decision.answer_kind,
        "answer_anchors": list(decision.answer_anchors),
        "anchored": decision.anchored,
        "kind_consistent": decision.kind_consistent,
        "check_failures": list(decision.check_failures),
        "reason": decision.reason,
    }
