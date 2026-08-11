"""Offline evaluation flow for the E1d RequestedFact (RF1) architecture spike.

Evaluation-only. Nothing here is imported by production code.

Runs the three-stage RF1 architecture over direct-drive dev cases (evidence
inline, no retrieval) with a provider that speaks the requested-fact
contracts:

1. STAGE 1 (``requested_fact``): derive a :class:`RequestedFactV1` from the
   TRUSTED QUESTION ONLY (no evidence is ever visible in this call).
   Server-validated by ``validate_requested_fact_output``. A malformed
   derivation is fail-closed: 1 call, invalid outcome, ``supported=false``,
   and the case stops.
2. STAGE 2 (``selector``): proof selection with the same exact-quote contract
   as E1c; server provenance validation reuses ``verifier_proof`` unchanged.
   An empty/invalid proof is fail-closed: ``supported=false`` and stage 3 is
   never called.
3. STAGE 3 (``answerability``): the model answers over the server-built
   isolation payload (question + requested fact + verified proofs ONLY, built
   by ``build_answerability_payload``; malicious sibling chunks cannot
   appear). The extracted answer is anchored and kind-checked
   deterministically by ``validate_answerability_decision``.

Every stage attempt is recorded in a call ledger
(:class:`RequestedFactCallRecord`), and the composed per-case outcome carries
the full requested-fact/proof/answerability derivation. Provider/transport
failures map to :class:`VerifierProviderError` and may abort the run via
``stop_on_provider_error``; invalid outputs are measurements (recorded, never
repaired, never retried).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from app.evaluation import sufficiency_metrics
from app.evaluation.verifier import EvidenceItem, VerifierProviderError
from app.evaluation.verifier_dev_cases import case_evidence_items
from app.evaluation.verifier_proof import (
    MissingValidProofError,
    ProofDecisionV1,
    ProofOutputError,
    UnknownProofSourceError,
    build_verified_bundle,
    validate_proof_decision,
)
from app.evaluation.verifier_proof_eval import MalformedProofOutputError
from app.evaluation.verifier_requested_fact import (
    ANSWERABILITY_SCHEMA_VERSION,
    REQUESTED_FACT_SCHEMA_VERSION,
    AnswerabilityDecisionV1,
    AnswerAnchoringError,
    MalformedAnswerabilityOutputError,
    MalformedRequestedFactError,
    RequestedFactV1,
    answerability_to_dict,
    build_answerability_payload,
    compose_requested_fact_supported,
    requested_fact_to_dict,
    validate_answerability_decision,
    validate_requested_fact_output,
)
from app.evaluation.verifier_requested_fact_prompts import (
    build_answerability_messages,
    build_requested_fact_messages,
    build_requested_fact_selector_messages,
)

ARCHITECTURE_RF1 = "RF1"

STAGE_REQUESTED_FACT = "requested_fact"
STAGE_SELECTOR = "selector"
STAGE_ANSWERABILITY = "answerability"

PLANNED_CALLS_PER_CASE = 3

_ANSWERABILITY_CONTRACT = "answer_anchors"


class RequestedFactProvider(Protocol):
    """Contract every RF1 provider implements.

    ``complete`` returns the parsed JSON object produced by the model (the raw
    requested-fact/selector/answerability claim; envelope extraction is the
    adapter's job). Model text that is not a JSON object raises
    :class:`MalformedProofOutputError`; transport failures raise
    :class:`VerifierProviderError`.
    """

    @property
    def model_name(self) -> str: ...

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]: ...


class MockRequestedFactProvider:
    """Deterministic scripted requested-fact provider (offline infrastructure only).

    ``respond_fn`` may be injected to script stage outcomes; results have NO
    semantic meaning. The default dispatches on the system prompt: stage 1
    derives a value-kind fact, stage 2 quotes the first evidence item, stage 3
    returns that quote's text verbatim as an anchored value answer.
    """

    def __init__(
        self,
        respond_fn: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None,
        model_name: str = "mock-requested-fact",
    ):
        self._respond_fn = respond_fn or _default_mock_response
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return self._respond_fn(messages)


def _default_mock_response(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Default fake rules for the three RF1 stages.

    Dispatches on the system prompt: the stage-1 prompt names
    ``question_kind``; the stage-2 prompt carries the proof contract; the
    stage-3 prompt names ``answer_anchors``.
    """
    system = messages[0]["content"] if messages else ""
    if "question_kind" in system:
        return {
            "schema_version": REQUESTED_FACT_SCHEMA_VERSION,
            "question_kind": "value",
            "expected_answer_kind": "text",
            "requires_explicit_value": True,
            "subject": "subject",
            "requested_attribute": "attribute",
            "proposition": "The question asks for a stated value.",
            "polarity": "affirmative",
        }
    user = messages[-1]["content"]
    if _ANSWERABILITY_CONTRACT in system:
        quote = _quote_from_verified_proofs(user)
        if quote is None:
            return {
                "status": "insufficient",
                "answer": None,
                "answer_kind": None,
                "answer_anchors": [],
                "reason": "infrastructure mock: no verified proof quote found",
            }
        return {
            "status": "answered",
            "answer": quote[: min(len(quote), 200)],
            "answer_kind": "value",
            "answer_anchors": [0],
            "reason": "infrastructure mock",
        }
    for line in user.splitlines():
        if line.startswith("[1] source_id:"):
            source_id = line.split("source_id:", 1)[1].strip()
            quote = _quote_from_user(user, source_id)
            if quote is not None:
                return {
                    "supported": True,
                    "proofs": [{"source_id": source_id, "quote": quote}],
                }
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


def _quote_from_verified_proofs(user: str) -> str | None:
    start_marker = "    <quote-text>\n"
    start = user.find(start_marker)
    if start == -1:
        return None
    start += len(start_marker)
    end = user.find("\n    </quote-text>", start)
    if end == -1:
        return None
    quote = user[start:end]
    if not quote.strip():
        return None
    return quote


@dataclass(frozen=True)
class RequestedFactCallRecord:
    """One ledger entry per stage attempt."""

    case_id: str
    stage: str
    attempted: bool
    successful: bool
    provider_failure: bool
    structural_valid: bool
    proof_valid: bool
    answer_anchored: bool
    final_supported: bool


@dataclass(frozen=True)
class RequestedFactCaseOutcome:
    """Composed per-case outcome with the full supported derivation."""

    case_id: str
    category: str
    answerable: bool
    supported: bool
    invalid: bool
    error_kind: str | None = None
    error: str | None = None
    fact: RequestedFactV1 | None = None
    proof: ProofDecisionV1 | None = None
    answerability: AnswerabilityDecisionV1 | None = None


@dataclass
class RequestedFactEvaluation:
    """Full evaluation: outcomes, stage-level ledger, metrics, budgets."""

    outcomes: list[RequestedFactCaseOutcome]
    ledger: list[RequestedFactCallRecord]
    metrics: dict[str, Any]
    invalid_outputs: list[RequestedFactCaseOutcome]
    false_supports: list[RequestedFactCaseOutcome]
    false_rejections: list[RequestedFactCaseOutcome]
    planned_calls: int
    verifier_calls: int = 0


class RequestedFactProviderAbortError(RuntimeError):
    """Fail-fast provider error carrying results captured before the failure."""

    def __init__(self, case_id: str, evaluation: RequestedFactEvaluation):
        super().__init__(f"requested-fact provider failed for case {case_id}")
        self.case_id = case_id
        self.evaluation = evaluation


def _error_kind(error: Exception) -> str:
    if isinstance(error, UnknownProofSourceError):
        return "evidence_source_validation"
    if isinstance(error, MissingValidProofError):
        return "proof_invalid"
    if isinstance(error, AnswerAnchoringError):
        return "answerability_invariant"
    if isinstance(error, (MalformedRequestedFactError, MalformedAnswerabilityOutputError)):
        return "malformed_output"
    return "malformed_output"


def _record(
    case_id: str,
    stage: str,
    *,
    attempted: bool = True,
    successful: bool = True,
    provider_failure: bool = False,
    structural_valid: bool = True,
    proof_valid: bool = True,
    answer_anchored: bool = False,
    final_supported: bool = False,
) -> RequestedFactCallRecord:
    return RequestedFactCallRecord(
        case_id=case_id,
        stage=stage,
        attempted=attempted,
        successful=successful,
        provider_failure=provider_failure,
        structural_valid=structural_valid,
        proof_valid=proof_valid,
        answer_anchored=answer_anchored,
        final_supported=final_supported,
    )


async def run_requested_fact_evaluation(
    cases: Sequence[dict[str, Any]],
    provider: RequestedFactProvider,
    *,
    stop_on_provider_error: bool = False,
) -> RequestedFactEvaluation:
    """Run the RF1 architecture over direct-drive cases.

    Invalid outputs are never silently accepted: they are captured per case as
    controlled evaluation errors (recorded in the ledger and the
    ``invalid_outputs`` list) and can never become ``supported``. Planned
    calls are 3 per case; actual calls are <= planned (fail-closed savings).
    """
    outcomes: list[RequestedFactCaseOutcome] = []
    ledger: list[RequestedFactCallRecord] = []
    verifier_calls = 0
    for case in sorted(cases, key=lambda c: c["id"]):
        case_id = case["id"]
        evidence = case_evidence_items(case)
        sources = {item.source_id: item.content for item in evidence}
        outcome, records, stage_calls = await _run_case(
            case_id,
            case["question"],
            case["category"],
            case["expected_supported"],
            evidence,
            sources,
            provider,
        )
        records = _with_final_supported(records, outcome.supported)
        ledger.extend(records)
        verifier_calls += stage_calls
        outcomes.append(outcome)
        if stop_on_provider_error and outcome.invalid and outcome.error_kind == "provider_error":
            raise RequestedFactProviderAbortError(
                case_id, _build_evaluation(outcomes, ledger, verifier_calls)
            )

    return _build_evaluation(outcomes, ledger, verifier_calls)


async def _run_case(
    case_id: str,
    question: str,
    category: str,
    answerable: bool,
    evidence: Sequence[EvidenceItem],
    sources: dict[str, str],
    provider: RequestedFactProvider,
) -> tuple[RequestedFactCaseOutcome, list[RequestedFactCallRecord], int]:
    """Three-stage RF1 case: fact derivation, proof selection, answerability."""
    records: list[RequestedFactCallRecord] = []

    # ---- STAGE 1: requested-fact derivation (QUESTION ONLY) ----
    try:
        raw = await provider.complete(build_requested_fact_messages(question))
    except VerifierProviderError as error:
        records.append(
            _record(case_id, STAGE_REQUESTED_FACT, successful=False, provider_failure=True)
        )
        return (
            _invalid_outcome(case_id, category, answerable, "provider_error", str(error)),
            records,
            1,
        )
    except MalformedProofOutputError as error:
        records.append(
            _record(case_id, STAGE_REQUESTED_FACT, successful=True, structural_valid=False)
        )
        # Fail-closed: a malformed derivation never reaches stages 2/3.
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            1,
        )
    try:
        fact = validate_requested_fact_output(raw)
    except MalformedRequestedFactError as error:
        records.append(_record(case_id, STAGE_REQUESTED_FACT, successful=True, proof_valid=False))
        # Fail-closed: an invalid derivation never reaches stages 2/3.
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            1,
        )
    records.append(_record(case_id, STAGE_REQUESTED_FACT, successful=True, structural_valid=True))

    # ---- STAGE 2: proof selection (reuses the E1c proof contract) ----
    try:
        raw = await provider.complete(
            build_requested_fact_selector_messages(question, fact, evidence)
        )
    except VerifierProviderError as error:
        records.append(_record(case_id, STAGE_SELECTOR, successful=False, provider_failure=True))
        return (
            _invalid_outcome(case_id, category, answerable, "provider_error", str(error)),
            records,
            2,
        )
    except MalformedProofOutputError as error:
        records.append(_record(case_id, STAGE_SELECTOR, successful=True, structural_valid=False))
        # Fail-closed: an invalid stage-2 output never reaches stage 3.
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            2,
        )
    try:
        decision = validate_proof_decision(raw, sources)
    except ProofOutputError as error:
        records.append(_record(case_id, STAGE_SELECTOR, successful=True, proof_valid=False))
        # Fail-closed: an invalid/empty proof means supported=false, no stage 3.
        return (
            _invalid_outcome(case_id, category, answerable, _error_kind(error), str(error)),
            records,
            2,
        )

    if not decision.supported:
        records.append(_record(case_id, STAGE_SELECTOR, successful=True, proof_valid=False))
        return (
            _case_outcome(case_id, category, answerable, fact=fact, proof=decision),
            records,
            2,
        )
    records.append(_record(case_id, STAGE_SELECTOR, successful=True, proof_valid=True))
    bundle = build_verified_bundle(decision)

    # ---- STAGE 3: answerability over verified proofs only ----
    try:
        payload = build_answerability_payload(question, fact, bundle, sources)
    except ProofOutputError as error:
        records.append(_record(case_id, STAGE_ANSWERABILITY, successful=True, proof_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, _error_kind(error), str(error)),
            records,
            3,
        )
    except AnswerAnchoringError as error:
        records.append(_record(case_id, STAGE_ANSWERABILITY, successful=True, proof_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, "answerability_invariant", str(error)),
            records,
            3,
        )
    try:
        raw = await provider.complete(build_answerability_messages(payload))
    except VerifierProviderError as error:
        records.append(
            _record(case_id, STAGE_ANSWERABILITY, successful=False, provider_failure=True)
        )
        return (
            _invalid_outcome(case_id, category, answerable, "provider_error", str(error)),
            records,
            3,
        )
    except MalformedProofOutputError as error:
        records.append(
            _record(case_id, STAGE_ANSWERABILITY, successful=True, structural_valid=False)
        )
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            3,
        )
    try:
        answerability = validate_answerability_decision(raw, bundle, fact)
    except MalformedAnswerabilityOutputError as error:
        records.append(_record(case_id, STAGE_ANSWERABILITY, successful=True, proof_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            3,
        )
    records.append(
        _record(
            case_id,
            STAGE_ANSWERABILITY,
            successful=True,
            structural_valid=True,
            proof_valid=True,
            answer_anchored=answerability.anchored,
        )
    )
    return (
        _case_outcome(
            case_id,
            category,
            answerable,
            fact=fact,
            proof=decision,
            answerability=answerability,
        ),
        records,
        3,
    )


def _invalid_outcome(
    case_id: str,
    category: str,
    answerable: bool,
    error_kind: str,
    error: str,
) -> RequestedFactCaseOutcome:
    return RequestedFactCaseOutcome(
        case_id=case_id,
        category=category,
        answerable=answerable,
        supported=False,
        invalid=True,
        error_kind=error_kind,
        error=error,
    )


def _case_outcome(
    case_id: str,
    category: str,
    answerable: bool,
    *,
    fact: RequestedFactV1,
    proof: ProofDecisionV1,
    answerability: AnswerabilityDecisionV1 | None = None,
) -> RequestedFactCaseOutcome:
    supported = compose_requested_fact_supported(proof, answerability)
    return RequestedFactCaseOutcome(
        case_id=case_id,
        category=category,
        answerable=answerable,
        supported=supported,
        invalid=False,
        fact=fact,
        proof=proof,
        answerability=answerability,
    )


def _build_evaluation(
    outcomes: list[RequestedFactCaseOutcome],
    ledger: list[RequestedFactCallRecord],
    verifier_calls: int,
) -> RequestedFactEvaluation:
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
    planned_calls = len(outcomes) * PLANNED_CALLS_PER_CASE
    return RequestedFactEvaluation(
        outcomes=outcomes,
        ledger=ledger,
        metrics=metrics,
        invalid_outputs=invalid_outputs,
        false_supports=false_supports,
        false_rejections=false_rejections,
        planned_calls=planned_calls,
        verifier_calls=verifier_calls,
    )


def _with_final_supported(
    records: list[RequestedFactCallRecord], supported: bool
) -> list[RequestedFactCallRecord]:
    """Stamp the composed final supported onto the case's last ledger record."""
    if not records:
        return records
    updated = [replace(records[-1], final_supported=supported)]
    return records[:-1] + updated


# ---------------------------------------------------------------------------
# Serialization / report helpers
# ---------------------------------------------------------------------------


def call_record_to_dict(record: RequestedFactCallRecord) -> dict[str, Any]:
    return {
        "case_id": record.case_id,
        "stage": record.stage,
        "attempted": record.attempted,
        "successful": record.successful,
        "provider_failure": record.provider_failure,
        "structural_valid": record.structural_valid,
        "proof_valid": record.proof_valid,
        "answer_anchored": record.answer_anchored,
        "final_supported": record.final_supported,
    }


def outcome_to_dict(outcome: RequestedFactCaseOutcome) -> dict[str, Any]:
    data: dict[str, Any] = {
        "case_id": outcome.case_id,
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
    if outcome.fact is not None:
        data["requested_fact"] = requested_fact_to_dict(outcome.fact)
    if outcome.proof is not None:
        data["proof_decision"] = _proof_decision_to_dict(outcome.proof)
    if outcome.answerability is not None:
        data["answerability_decision"] = answerability_to_dict(outcome.answerability)
    return data


def _proof_decision_to_dict(decision: ProofDecisionV1) -> dict[str, Any]:
    return {
        "supported": decision.supported,
        "proofs": [
            {
                "source_id": p.source_id,
                "quote": p.quote,
                "start_offset": p.start_offset,
                "end_offset": p.end_offset,
                "status": p.status,
            }
            for p in decision.proofs
        ],
        "invalid_proofs": [
            {
                "source_id": p.source_id,
                "quote": p.quote,
                "status": p.status,
                "reason": p.reason,
            }
            for p in decision.invalid_proofs
        ],
    }


def _derivation_text(outcome: RequestedFactCaseOutcome) -> str:
    if outcome.invalid:
        return (
            f"supported=false (invalid output: {outcome.error_kind}); "
            f"measured, never repaired, never retried"
        )
    if outcome.proof is None or outcome.answerability is None:
        return "supported=false (fail-closed: no stage-3 call)"
    decision = outcome.answerability
    if decision.status == "answered":
        return (
            f"supported=(proof valid AND status==answered AND answer non-empty AND "
            f"anchored AND kind_consistent); status=answered, answer={decision.answer!r}, "
            f"anchored={decision.anchored}, kind_consistent={decision.kind_consistent} => "
            f"{outcome.supported}"
        )
    return (
        f"supported=false (answerability status={decision.status!r}); "
        f"check_failures={decision.check_failures}"
    )


def build_requested_fact_json_report(
    *,
    architecture: str,
    dataset_path: str,
    dataset_version: str,
    provider: str,
    model: str,
    external_api: bool,
    runtime_seconds: float | None,
    git_commit: str | None,
    evaluation: RequestedFactEvaluation,
    max_calls: int | None = None,
) -> dict[str, Any]:
    """Assemble the machine-readable E1d requested-fact spike report."""
    benchmark: dict[str, Any] = {
        "kind": "requested_fact",
        "requested_fact_schema_version": REQUESTED_FACT_SCHEMA_VERSION,
        "answerability_schema_version": ANSWERABILITY_SCHEMA_VERSION,
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
            "stage_1_requested_fact": (
                "RequestedFactV1 derived from the TRUSTED QUESTION ONLY; no evidence "
                "is ever visible in this call (architectural isolation). Server "
                "validation: unknown keys rejected, version pinned, enums enforced, "
                "cross-field value-vs-existence consistency, free-text hygiene."
            ),
            "stage_2_selector": (
                "Proof selection reuses the E1c exact-quote contract; every quote "
                "must be an EXACT substring of its cited source under minimal "
                "canonicalization (CRLF/CR -> LF only). No case folding, no "
                "whitespace collapsing, no fuzzy matching."
            ),
            "stage_3_answerability": (
                "Answerability input is built SERVER-SIDE from verified proofs only: "
                "question + requested fact + quote + full content of that cited "
                "source only. Malicious sibling chunks never present (test-proven). "
                "The extracted answer must anchor (Path V: literal containment; "
                "Path B: controlled yes/no vocabulary + anchor) and match the "
                "answer-kind matrix, else the claimed answer is contradicted."
            ),
            "value_vs_existence": (
                "requires_explicit_value=true: an absence statement can never supply "
                "the requested value -> insufficient -> NOT supported. "
                "requires_explicit_value=false: a subject/attribute-aligned absence "
                "statement is a valid answered='no'."
            ),
            "fail_closed": (
                "Stage-1 malformed derivation: 1 call, invalid, supported=false, STOP. "
                "Stage-2 empty/invalid proof: supported=false, stage 3 never called. "
                "Stage-3 malformed answerability: 3 calls, invalid. Provider/transport "
                "failure: abort with a persisted partial report (exit 3)."
            ),
            "isolation_guarantee": (
                "The stage-3 payload is built SERVER-SIDE via "
                "build_answerability_payload from verified proofs only; no sibling "
                "chunk text, no raw evidence bundle, and no evaluation metadata can "
                "appear in the model input by construction."
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


def render_requested_fact_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    lines: list[str] = []
    lines.append("# RequestedFact (RF1) Architecture Spike")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Requested-fact schema version: {benchmark['requested_fact_schema_version']}")
    lines.append(f"- Answerability schema version: {benchmark['answerability_schema_version']}")
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
        "| case_id | stage | attempted | successful | provider_failure | "
        "structural_valid | proof_valid | answer_anchored | final_supported |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for record in report["call_ledger"]:
        lines.append(
            f"| {record['case_id']} | {record['stage']} | {record['attempted']} | "
            f"{record['successful']} | {record['provider_failure']} | "
            f"{record['structural_valid']} | {record['proof_valid']} | "
            f"{record['answer_anchored']} | {record['final_supported']} |"
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
        if "requested_fact" in outcome:
            fact = outcome["requested_fact"]
            lines.append(
                f"- Requested fact: kind={fact['question_kind']}, "
                f"expected={fact['expected_answer_kind']}, "
                f"requires_explicit_value={fact['requires_explicit_value']}, "
                f"polarity={fact['polarity']}"
            )
            lines.append(f"  - subject: {fact['subject']}")
            lines.append(f"  - requested_attribute: {fact['requested_attribute']}")
            lines.append(f"  - proposition: {fact['proposition']}")
        if "proof_decision" in outcome:
            proof = outcome["proof_decision"]
            lines.append(
                f"- Proof: supported={proof['supported']}, "
                f"valid proofs={len(proof['proofs'])}, "
                f"invalid proofs={len(proof['invalid_proofs'])}"
            )
            for invalid in proof["invalid_proofs"]:
                lines.append(
                    f"  - dropped: {invalid['source_id']} status={invalid['status']} "
                    f"({invalid['reason']})"
                )
        if "answerability_decision" in outcome:
            answerability = outcome["answerability_decision"]
            lines.append(
                f"- Answerability: status={answerability['status']}, "
                f"answer={answerability['answer']!r}, "
                f"answer_kind={answerability['answer_kind']}, "
                f"anchors={answerability['answer_anchors']}, "
                f"anchored={answerability['anchored']}, "
                f"kind_consistent={answerability['kind_consistent']}"
            )
            if answerability["check_failures"]:
                lines.append(f"  - check failures: {', '.join(answerability['check_failures'])}")
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
