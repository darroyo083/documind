"""Offline evaluation flow for the evidence verifier (PoC 3F-A).

Preferred flow:

    load dataset
    -> build existing synthetic corpus
    -> run real production retrieval (reused from runner)
    -> create verifier-safe evidence payload
    -> verifier decision
    -> strict output validation
    -> compare with answerable ground truth
    -> classification metrics

Retrieval is reused exactly as PoC 3C/3E do; it is never reimplemented here.
The production-like retrieval configuration for a real verifier benchmark is:
local FastEmbed (BAAI/bge-small-en-v1.5, 384 dims), top_k 5, benchmark
threshold 0.5. The 0.2 default in ``config.py`` is the application default,
NOT the benchmark threshold.

Zero-evidence short circuit: when retrieval returns zero candidates there is
nothing for an evidence verifier to verify. The query is classified
unsupported immediately (reason ``insufficient_evidence``) and the provider is
NOT called. This matches existing no-context Q&A semantics, avoids needless
cost, and makes expected external-call counts honest: one verifier call per
query that actually retrieved at least one candidate. ``verifier_calls`` on
the result counts exactly those provider invocations.

Split terminology: the historical 13-query "holdout" was exposed to all
candidate configurations during PoC 3E development and is no longer pristine.
This harness labels that set REGRESSION, never "untouched holdout". A fresh v2
holdout must be constructed only after the verifier design and prompt are
frozen; this task does not create one. Split labels map through
:func:`split_label`, so a future dataset can introduce new split names without
redesigning the evaluator.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.evaluation import sufficiency_metrics
from app.evaluation.runner import QueryResult
from app.evaluation.verifier import (
    EvidenceVerifier,
    ReasonCode,
    UnknownEvidenceSourceError,
    VerifierOutputError,
    VerifierProviderError,
    decision_to_dict,
    validate_decision,
)
from app.evaluation.verifier_payload import build_evidence_items

REGRESSION_LABEL = "regression"
HOLDOUT_DATASET_SPLIT = "holdout"
REPORTED_SPLIT_LABELS = {"dev": "dev", "holdout": REGRESSION_LABEL}


def split_label(dataset_split: str) -> str:
    """Map a dataset split value to the reported label.

    The historical 'holdout' is reported as 'regression' because it is not a
    pristine holdout. Unknown values pass through unchanged so a future v2
    dataset can carry its own split names.
    """
    return REPORTED_SPLIT_LABELS.get(dataset_split, dataset_split)


@dataclass(frozen=True)
class VerifierOutcome:
    query_id: str
    split: str
    scope: str
    category: str
    answerable: bool
    question: str
    supported: bool | None
    reason: str | None
    evidence_source_ids: list[str]
    evidence_count: int
    evidence_ids: list[str]
    invalid: bool
    error_kind: str | None = None
    error: str | None = None


@dataclass
class VerifierEvaluation:
    outcomes: list[VerifierOutcome]
    metrics: dict[str, Any]
    invalid_outputs: list[VerifierOutcome]
    evidence_validation_failures: list[VerifierOutcome]
    false_supports: list[VerifierOutcome]
    false_rejections: list[VerifierOutcome]
    verifier_calls: int = 0


def _error_kind(error: VerifierOutputError) -> str:
    if isinstance(error, UnknownEvidenceSourceError):
        return "evidence_source_validation"
    if isinstance(error, VerifierProviderError):
        return "provider_error"
    return "malformed_output"


async def run_verifier_evaluation(
    results: Sequence[QueryResult],
    verifier: EvidenceVerifier,
    split_by_id: dict[str, str],
) -> VerifierEvaluation:
    """Run the verifier over every retrieval result and validate outputs.

    Queries with zero retrieved candidates short-circuit to unsupported
    (reason ``insufficient_evidence``) WITHOUT calling the provider. The
    provider is invoked once per query that has at least one evidence item;
    ``verifier_calls`` counts exactly those invocations.

    Invalid verifier output is never silently accepted: it is captured per
    query as a controlled evaluation error and excluded from classification
    metrics (reported separately).
    """
    outcomes: list[VerifierOutcome] = []
    verifier_calls = 0
    for result in sorted(results, key=lambda r: r.id):
        evidence = build_evidence_items(result)
        allowed = {item.source_id for item in evidence}
        if not evidence:
            outcomes.append(
                VerifierOutcome(
                    query_id=result.id,
                    split=split_label(split_by_id.get(result.id, "dev")),
                    scope=result.scope,
                    category=result.category,
                    answerable=result.answerable,
                    question=result.question,
                    supported=False,
                    reason=ReasonCode.INSUFFICIENT_EVIDENCE.value,
                    evidence_source_ids=[],
                    evidence_count=0,
                    evidence_ids=[],
                    invalid=False,
                )
            )
            continue
        verifier_calls += 1
        try:
            decision = await verifier.verify(result.question, evidence)
            decision = validate_decision(decision_to_dict(decision), allowed)
        except VerifierOutputError as error:
            outcomes.append(
                VerifierOutcome(
                    query_id=result.id,
                    split=split_label(split_by_id.get(result.id, "dev")),
                    scope=result.scope,
                    category=result.category,
                    answerable=result.answerable,
                    question=result.question,
                    supported=None,
                    reason=None,
                    evidence_source_ids=[],
                    evidence_count=len(evidence),
                    evidence_ids=[item.source_id for item in evidence],
                    invalid=True,
                    error_kind=_error_kind(error),
                    error=str(error),
                )
            )
            continue
        outcomes.append(
            VerifierOutcome(
                query_id=result.id,
                split=split_label(split_by_id.get(result.id, "dev")),
                scope=result.scope,
                category=result.category,
                answerable=result.answerable,
                question=result.question,
                supported=decision.supported,
                reason=decision.reason,
                evidence_source_ids=decision.evidence_source_ids,
                evidence_count=len(evidence),
                evidence_ids=[item.source_id for item in evidence],
                invalid=False,
            )
        )

    invalid_outputs = [o for o in outcomes if o.invalid]
    evidence_validation_failures = [
        o for o in outcomes if o.error_kind == "evidence_source_validation"
    ]
    false_supports = [o for o in outcomes if not o.invalid and not o.answerable and o.supported]
    false_rejections = [o for o in outcomes if not o.invalid and o.answerable and not o.supported]

    return VerifierEvaluation(
        outcomes=outcomes,
        metrics=group_verifier_metrics(outcomes),
        invalid_outputs=invalid_outputs,
        evidence_validation_failures=evidence_validation_failures,
        false_supports=false_supports,
        false_rejections=false_rejections,
        verifier_calls=verifier_calls,
    )


def group_verifier_metrics(outcomes: Sequence[VerifierOutcome]) -> dict[str, Any]:
    """Classification metrics for overall + split + scope + category groups.

    Reuses ``sufficiency_metrics.classification_metrics`` unchanged.
    """
    valid = [o for o in outcomes if not o.invalid]
    groups: dict[str, list[VerifierOutcome]] = {"overall": valid}
    for split in sorted({o.split for o in valid}):
        groups[f"split:{split}"] = [o for o in valid if o.split == split]
    for scope in ("private", "reference", "combined"):
        groups[scope] = [o for o in valid if o.scope == scope]
    for category in sorted({o.category for o in valid}):
        groups[f"category:{category}"] = [o for o in valid if o.category == category]
    return {
        name: sufficiency_metrics.classification_metrics(
            [o.answerable for o in group],
            [bool(o.supported) for o in group],
        )
        for name, group in groups.items()
        if group
    }
