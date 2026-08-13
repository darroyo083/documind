"""Offline evaluation flow for the AB2 attribute-binding architecture.

Evaluation-only. Runs the three-stage AB2 architecture over direct-drive dev
cases with a provider that speaks the AB2 contracts:

1. STAGE 1 (``requested_fact``): reuse the RF1 requested-fact derivation from
   the trusted question only.
2. STAGE 2 (``selector``): reuse the RF1/E1c exact-quote proof contract.
3. STAGE 3 (``extractor``): the model independently extracts an
   :class:`ExtractedFactV1` over the server-built verified-proofs payload; the
   server deterministically validates anchoring, polarity, and kind, then
   composes ``supported`` fail-closed.

Every stage attempt is recorded in a call ledger; provider/transport failures
map to :class:`VerifierProviderError` and may abort via ``stop_on_provider_error``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from app.evaluation import sufficiency_metrics
from app.evaluation.verifier import EvidenceItem, VerifierProviderError
from app.evaluation.verifier_attribute_binding import (
    EXTRACTED_FACT_SCHEMA_VERSION,
    ExtractedFactAnchoringError,
    ExtractedFactV1,
    MalformedExtractedFactError,
    build_extracted_fact_payload,
    compose_attribute_binding_supported,
    extracted_fact_to_dict,
    validate_extracted_fact,
)
from app.evaluation.verifier_attribute_binding_prompts import (
    build_extractor_messages,
    build_stage1_messages,
    build_stage2_messages,
)
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
    MalformedRequestedFactError,
    RequestedFactV1,
    requested_fact_to_dict,
    validate_requested_fact_output,
)

ARCHITECTURE_AB2 = "AB2"

STAGE_REQUESTED_FACT = "requested_fact"
STAGE_SELECTOR = "selector"
STAGE_EXTRACTOR = "extractor"

PLANNED_CALLS_PER_CASE = 3


class AttributeBindingProvider(Protocol):
    """Contract every AB2 provider implements."""

    @property
    def model_name(self) -> str: ...

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]: ...


class MockAttributeBindingProvider:
    """Deterministic scripted AB2 provider (offline infrastructure only)."""

    def __init__(
        self,
        respond_fn: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None,
        model_name: str = "mock-attribute-binding",
    ):
        self._respond_fn = respond_fn or _default_mock_response
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return self._respond_fn(messages)


def _default_mock_response(messages: list[dict[str, str]]) -> dict[str, Any]:
    system = messages[0]["content"] if messages else ""
    if "question_kind" in system and "extracted_fact_v1" not in system:
        return {
            "schema_version": "requested_fact_v1",
            "question_kind": "value",
            "expected_answer_kind": "text",
            "requires_explicit_value": True,
            "subject": "subject",
            "requested_attribute": "attribute",
            "proposition": "The question asks for a stated value.",
            "polarity": "affirmative",
        }
    user = messages[-1]["content"]
    if "extracted_fact_v1" in system:
        quote = _quote_from_verified_proofs(user)
        if quote is None:
            return {
                "schema_version": EXTRACTED_FACT_SCHEMA_VERSION,
                "status": "no_fact",
                "subject": None,
                "attribute": None,
                "value": None,
                "value_kind": None,
                "polarity": "unspecified",
                "fact_anchors": [],
                "reason": "infrastructure mock: no verified proof quote found",
            }
        value = quote[: min(len(quote), 200)]
        return {
            "schema_version": EXTRACTED_FACT_SCHEMA_VERSION,
            "status": "fact_extracted",
            "subject": "subject",
            "attribute": "attribute",
            "value": value,
            "value_kind": "text",
            "polarity": "affirmative",
            "fact_anchors": [0],
            "reason": "infrastructure mock",
        }
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
class AttributeBindingCallRecord:
    case_id: str
    stage: str
    attempted: bool
    successful: bool
    provider_failure: bool
    structural_valid: bool
    proof_valid: bool
    value_anchored: bool
    final_supported: bool


@dataclass(frozen=True)
class AttributeBindingCaseOutcome:
    case_id: str
    category: str
    answerable: bool
    supported: bool
    invalid: bool
    error_kind: str | None = None
    error: str | None = None
    fact: RequestedFactV1 | None = None
    proof: ProofDecisionV1 | None = None
    extracted: ExtractedFactV1 | None = None


@dataclass
class AttributeBindingEvaluation:
    outcomes: list[AttributeBindingCaseOutcome]
    ledger: list[AttributeBindingCallRecord]
    metrics: dict[str, Any]
    invalid_outputs: list[AttributeBindingCaseOutcome]
    false_supports: list[AttributeBindingCaseOutcome]
    false_rejections: list[AttributeBindingCaseOutcome]
    planned_calls: int
    verifier_calls: int = 0


class AttributeBindingProviderAbortError(RuntimeError):
    def __init__(self, case_id: str, evaluation: AttributeBindingEvaluation):
        super().__init__(f"attribute-binding provider failed for case {case_id}")
        self.case_id = case_id
        self.evaluation = evaluation


def _error_kind(error: Exception) -> str:
    if isinstance(error, UnknownProofSourceError):
        return "evidence_source_validation"
    if isinstance(error, MissingValidProofError):
        return "proof_invalid"
    if isinstance(error, ExtractedFactAnchoringError):
        return "extracted_fact_invariant"
    if isinstance(error, (MalformedRequestedFactError, MalformedExtractedFactError)):
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
    value_anchored: bool = False,
    final_supported: bool = False,
) -> AttributeBindingCallRecord:
    return AttributeBindingCallRecord(
        case_id=case_id,
        stage=stage,
        attempted=attempted,
        successful=successful,
        provider_failure=provider_failure,
        structural_valid=structural_valid,
        proof_valid=proof_valid,
        value_anchored=value_anchored,
        final_supported=final_supported,
    )


async def run_attribute_binding_evaluation(
    cases: Sequence[dict[str, Any]],
    provider: AttributeBindingProvider,
    *,
    stop_on_provider_error: bool = False,
    inter_call_delay_seconds: float = 0.0,
) -> AttributeBindingEvaluation:
    outcomes: list[AttributeBindingCaseOutcome] = []
    ledger: list[AttributeBindingCallRecord] = []
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
            inter_call_delay_seconds,
        )
        records = _with_final_supported(records, outcome.supported)
        ledger.extend(records)
        verifier_calls += stage_calls
        outcomes.append(outcome)
        if stop_on_provider_error and outcome.invalid and outcome.error_kind == "provider_error":
            raise AttributeBindingProviderAbortError(
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
    provider: AttributeBindingProvider,
    inter_call_delay_seconds: float = 0.0,
) -> tuple[AttributeBindingCaseOutcome, list[AttributeBindingCallRecord], int]:
    """Three-stage AB2 case: fact derivation, proof selection, extraction."""

    async def _pace() -> None:
        if inter_call_delay_seconds > 0:
            await asyncio.sleep(inter_call_delay_seconds)

    records: list[AttributeBindingCallRecord] = []

    # ---- STAGE 1: requested-fact derivation (QUESTION ONLY) ----
    await _pace()
    try:
        raw = await provider.complete(build_stage1_messages(question))
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
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            1,
        )
    try:
        fact = validate_requested_fact_output(raw)
    except MalformedRequestedFactError as error:
        records.append(_record(case_id, STAGE_REQUESTED_FACT, successful=True, proof_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            1,
        )
    records.append(_record(case_id, STAGE_REQUESTED_FACT, successful=True, structural_valid=True))

    # ---- STAGE 2: proof selection ----
    await _pace()
    try:
        raw = await provider.complete(build_stage2_messages(question, fact, evidence))
    except VerifierProviderError as error:
        records.append(_record(case_id, STAGE_SELECTOR, successful=False, provider_failure=True))
        return (
            _invalid_outcome(case_id, category, answerable, "provider_error", str(error)),
            records,
            2,
        )
    except MalformedProofOutputError as error:
        records.append(_record(case_id, STAGE_SELECTOR, successful=True, structural_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            2,
        )
    try:
        decision = validate_proof_decision(raw, sources)
    except ProofOutputError as error:
        records.append(_record(case_id, STAGE_SELECTOR, successful=True, proof_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, _error_kind(error), str(error)),
            records,
            2,
        )

    if not decision.supported:
        records.append(_record(case_id, STAGE_SELECTOR, successful=True, proof_valid=False))
        return _case_outcome(case_id, category, answerable, fact=fact, proof=decision), records, 2
    records.append(_record(case_id, STAGE_SELECTOR, successful=True, proof_valid=True))
    bundle = build_verified_bundle(decision)

    # ---- STAGE 3: independent fact extraction ----
    try:
        payload = build_extracted_fact_payload(question, fact, bundle, sources)
    except ProofOutputError as error:
        records.append(_record(case_id, STAGE_EXTRACTOR, successful=True, proof_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, _error_kind(error), str(error)),
            records,
            3,
        )
    except ExtractedFactAnchoringError as error:
        records.append(_record(case_id, STAGE_EXTRACTOR, successful=True, proof_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, "extracted_fact_invariant", str(error)),
            records,
            3,
        )
    await _pace()
    try:
        raw = await provider.complete(build_extractor_messages(payload))
    except VerifierProviderError as error:
        records.append(_record(case_id, STAGE_EXTRACTOR, successful=False, provider_failure=True))
        return (
            _invalid_outcome(case_id, category, answerable, "provider_error", str(error)),
            records,
            3,
        )
    except MalformedProofOutputError as error:
        records.append(_record(case_id, STAGE_EXTRACTOR, successful=True, structural_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            3,
        )
    try:
        extracted = validate_extracted_fact(raw, bundle, fact)
    except MalformedExtractedFactError as error:
        records.append(_record(case_id, STAGE_EXTRACTOR, successful=True, proof_valid=False))
        return (
            _invalid_outcome(case_id, category, answerable, "malformed_output", str(error)),
            records,
            3,
        )
    records.append(
        _record(
            case_id,
            STAGE_EXTRACTOR,
            successful=True,
            structural_valid=True,
            proof_valid=True,
            value_anchored=extracted.anchored,
        )
    )
    return (
        _case_outcome(
            case_id,
            category,
            answerable,
            fact=fact,
            proof=decision,
            extracted=extracted,
        ),
        records,
        3,
    )


def _invalid_outcome(
    case_id: str, category: str, answerable: bool, error_kind: str, error: str
) -> AttributeBindingCaseOutcome:
    return AttributeBindingCaseOutcome(
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
    extracted: ExtractedFactV1 | None = None,
) -> AttributeBindingCaseOutcome:
    supported = compose_attribute_binding_supported(proof, extracted, fact)
    return AttributeBindingCaseOutcome(
        case_id=case_id,
        category=category,
        answerable=answerable,
        supported=supported,
        invalid=False,
        fact=fact,
        proof=proof,
        extracted=extracted,
    )


def _build_evaluation(
    outcomes: list[AttributeBindingCaseOutcome],
    ledger: list[AttributeBindingCallRecord],
    verifier_calls: int,
) -> AttributeBindingEvaluation:
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
    return AttributeBindingEvaluation(
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
    records: list[AttributeBindingCallRecord], supported: bool
) -> list[AttributeBindingCallRecord]:
    if not records:
        return records
    updated = [replace(records[-1], final_supported=supported)]
    return records[:-1] + updated


# ---------------------------------------------------------------------------
# Serialization / report helpers
# ---------------------------------------------------------------------------


def call_record_to_dict(record: AttributeBindingCallRecord) -> dict[str, Any]:
    return {
        "case_id": record.case_id,
        "stage": record.stage,
        "attempted": record.attempted,
        "successful": record.successful,
        "provider_failure": record.provider_failure,
        "structural_valid": record.structural_valid,
        "proof_valid": record.proof_valid,
        "value_anchored": record.value_anchored,
        "final_supported": record.final_supported,
    }


def outcome_to_dict(outcome: AttributeBindingCaseOutcome) -> dict[str, Any]:
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
    if outcome.extracted is not None:
        data["extracted_fact"] = extracted_fact_to_dict(outcome.extracted)
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
            {"source_id": p.source_id, "quote": p.quote, "status": p.status, "reason": p.reason}
            for p in decision.invalid_proofs
        ],
    }


def _derivation_text(outcome: AttributeBindingCaseOutcome) -> str:
    if outcome.invalid:
        return (
            f"supported=false (invalid output: {outcome.error_kind}); "
            "measured, never repaired, never retried"
        )
    if outcome.proof is None or outcome.extracted is None:
        return "supported=false (fail-closed: no stage-3 call)"
    extracted = outcome.extracted
    if extracted.status == "fact_extracted":
        return (
            "supported=(proof valid AND status==fact_extracted AND "
            f"polarity={extracted.polarity!r} AND anchored={extracted.anchored} "
            f"AND check_failures={extracted.check_failures}) => {outcome.supported}"
        )
    return (
        f"supported=false (extracted status={extracted.status!r}, polarity={extracted.polarity!r})"
    )


def build_attribute_binding_json_report(
    *,
    architecture: str,
    dataset_path: str,
    dataset_version: str,
    provider: str,
    model: str,
    external_api: bool,
    runtime_seconds: float | None,
    git_commit: str | None,
    evaluation: AttributeBindingEvaluation,
    max_calls: int | None = None,
) -> dict[str, Any]:
    benchmark: dict[str, Any] = {
        "kind": "attribute_binding",
        "extracted_fact_schema_version": EXTRACTED_FACT_SCHEMA_VERSION,
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
                "RequestedFactV1 derived from the trusted question only (reused from RF1)."
            ),
            "stage_2_selector": "Exact-quote proof contract (reused from RF1/E1c).",
            "stage_3_extractor": (
                "Independent structured fact extraction over server-built verified "
                "proofs only. The extractor never sees the candidate/expected answer. "
                "A value claim requires polarity=affirmative and literal anchoring; "
                "absence/negation/unspecified polarity is deterministically unsupported."
            ),
            "fail_closed": (
                "Stage-1 malformed: 1 call, invalid, STOP. Stage-2 empty/invalid proof: "
                "supported=false, no stage 3. Stage-3 malformed: 3 calls, invalid. "
                "Provider failure: abort with persisted partial report (exit 3)."
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


def render_attribute_binding_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    lines: list[str] = []
    lines.append("# Attribute-Binding (AB2) Verifier Architecture")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Extracted-fact schema version: {benchmark['extracted_fact_schema_version']}")
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
                f"requires_explicit_value={fact['requires_explicit_value']}, "
                f"attribute={fact['requested_attribute']}"
            )
        if "extracted_fact" in outcome:
            extracted = outcome["extracted_fact"]
            lines.append(
                f"- Extracted fact: status={extracted['status']}, "
                f"value={extracted['value']!r}, polarity={extracted['polarity']}, "
                f"anchored={extracted['anchored']}, "
                f"check_failures={extracted['check_failures']}"
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
