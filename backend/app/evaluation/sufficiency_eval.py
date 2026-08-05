"""Offline evidence-sufficiency evaluation over existing retrieval results.

This module runs candidate abstention strategies over retrieval ``QueryResult``
objects (which carry candidate scores and candidate contents) and produces
classification metrics per strategy, split, scope, and category.

It is fully deterministic and does not depend on an answer provider or any LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.evaluation import sufficiency_metrics
from app.evaluation.runner import QueryResult
from app.evaluation.strategies import (
    StrategyConfig,
    evaluate_strategy,
    strategy_grids,
)


@dataclass(frozen=True)
class SufficiencyOutcome:
    query_id: str
    split: str
    scope: str
    category: str
    answerable: bool
    question: str
    supported: bool
    reason: str
    signals: dict[str, Any]


def compute_outcome(
    config: StrategyConfig,
    result: QueryResult,
    split_by_id: dict[str, str],
) -> SufficiencyOutcome:
    """Apply a strategy config to one retrieval result."""
    decision = evaluate_strategy(
        config,
        result.question,
        result.candidate_scores,
        result.candidate_contents,
    )
    return SufficiencyOutcome(
        query_id=result.id,
        split=split_by_id.get(result.id, "dev"),
        scope=result.scope,
        category=result.category,
        answerable=result.answerable,
        question=result.question,
        supported=decision.supported,
        reason=decision.reason,
        signals={
            "top1": decision.signals.top1,
            "top2": decision.signals.top2,
            "top3": decision.signals.top3,
            "margin": decision.signals.margin,
            "mean_top3": decision.signals.mean_top3,
            "mean_top5": decision.signals.mean_top5,
            "top1_minus_mean_rest": decision.signals.top1_minus_mean_rest,
            "retrieval_count": decision.signals.retrieval_count,
            "query_content_tokens": decision.signals.query_content_tokens,
            "lexical_coverage_top1": decision.signals.lexical_coverage_top1,
            "lexical_coverage_topk": decision.signals.lexical_coverage_topk,
        },
    )


def outcomes_for_config(
    config: StrategyConfig, results: list[QueryResult], split_by_id: dict[str, str]
) -> list[SufficiencyOutcome]:
    """Apply a config to all results, returning stable outcomes (sorted by id)."""
    return [
        compute_outcome(config, result, split_by_id)
        for result in sorted(results, key=lambda r: r.id)
    ]


def _metrics_for(outcomes: list[SufficiencyOutcome]) -> dict[str, Any]:
    return sufficiency_metrics.classification_metrics(
        [outcome.answerable for outcome in outcomes],
        [outcome.supported for outcome in outcomes],
    )


def group_metrics(outcomes: list[SufficiencyOutcome]) -> dict[str, Any]:
    """Metrics for overall + per-scope + per-category + per-split groups."""
    groups: dict[str, list[SufficiencyOutcome]] = {"overall": outcomes}
    for split in ("dev", "holdout"):
        groups[f"split:{split}"] = [o for o in outcomes if o.split == split]
    for scope in ("private", "reference", "combined"):
        groups[scope] = [o for o in outcomes if o.scope == scope]
    for category in sorted({o.category for o in outcomes}):
        groups[f"category:{category}"] = [o for o in outcomes if o.category == category]
    return {name: _metrics_for(group) for name, group in groups.items() if group}


def evaluate_config(
    config: StrategyConfig, results: list[QueryResult], split_by_id: dict[str, str]
) -> dict[str, Any]:
    """Full evaluation for one strategy config (metrics + per-query outcomes)."""
    outcomes = outcomes_for_config(config, results, split_by_id)
    return {
        "strategy": config.display(),
        "name": config.name,
        "params": config.params,
        "metrics": group_metrics(outcomes),
        "outcomes": [
            {
                "query_id": outcome.query_id,
                "split": outcome.split,
                "scope": outcome.scope,
                "category": outcome.category,
                "answerable": outcome.answerable,
                "question": outcome.question,
                "supported": outcome.supported,
                "reason": outcome.reason,
                "signals": outcome.signals,
            }
            for outcome in sorted(outcomes, key=lambda o: o.query_id)
        ],
    }


def grid_search_dev(
    results: list[QueryResult], split_by_id: dict[str, str]
) -> list[dict[str, Any]]:
    """Run every strategy config over the DEV subset only.

    Returns rows sorted deterministically by (balanced accuracy desc,
    answerable retention desc, unsupported detection desc, display name).
    """
    dev_results = [result for result in results if split_by_id.get(result.id) == "dev"]

    rows: list[dict[str, Any]] = []
    for name in (
        "max_score",
        "score_margin",
        "score_concentration",
        "lexical_top1",
        "lexical_topk",
        "combined",
    ):
        for params in strategy_grids()[name]:
            config = StrategyConfig(name=name, params=params)
            outcomes = outcomes_for_config(config, dev_results, split_by_id)
            metrics = _metrics_for(outcomes)
            row = {
                "strategy": config.display(),
                "name": name,
                "params": params,
                "answerable_retention": metrics["answerable_retention"],
                "unsupported_detection": metrics["unsupported_detection"],
                "supported_precision": metrics["supported_precision"],
                "unsupported_precision": metrics["unsupported_precision"],
                "false_rejection_rate": metrics["false_rejection_rate"],
                "false_support_rate": metrics["false_support_rate"],
                "balanced_accuracy": metrics["balanced_accuracy"],
                "accuracy": metrics["accuracy"],
            }
            rows.append(row)
    rows.sort(
        key=lambda row: (
            -row["balanced_accuracy"],
            -row["answerable_retention"],
            -row["unsupported_detection"],
            row["strategy"],
        )
    )
    return rows


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def _safe_float(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) else None


def feature_diagnostics(results: list[QueryResult], split_by_id: dict[str, str]) -> dict[str, Any]:
    """Mean/min/max of each signal for answerable vs unanswerable queries.

    Signals are computed from raw retrieval candidates before any strategy
    decision, so this documents whether the chosen features separate classes.
    """
    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]
    signals = [
        "top1",
        "top2",
        "top3",
        "margin",
        "mean_top3",
        "mean_top5",
        "top1_minus_mean_rest",
        "lexical_coverage_top1",
        "lexical_coverage_topk",
    ]
    groups: dict[str, dict[str, Any]] = {}
    for signal in signals:
        a_values: list[float] = []
        u_values: list[float] = []
        for result in [*answerable, *unanswerable]:
            signals_by_id = _signals_for_result(result)
            value = _safe_float(signals_by_id.get(signal))
            if value is None:
                continue
            if result.answerable:
                a_values.append(value)
            else:
                u_values.append(value)
        groups[signal] = {
            "answerable": _stats(a_values),
            "unanswerable": _stats(u_values),
        }
    return {
        "groups": groups,
        "split_by_id": dict(sorted(split_by_id.items())),
    }


def _signals_for_result(result: QueryResult) -> dict[str, Any]:
    from app.evaluation.sufficiency import compute_signals

    signals = compute_signals(result.question, result.candidate_scores, result.candidate_contents)
    return {
        "top1": signals.top1,
        "top2": signals.top2,
        "top3": signals.top3,
        "margin": signals.margin,
        "mean_top3": signals.mean_top3,
        "mean_top5": signals.mean_top5,
        "top1_minus_mean_rest": signals.top1_minus_mean_rest,
        "lexical_coverage_top1": signals.lexical_coverage_top1,
        "lexical_coverage_topk": signals.lexical_coverage_topk,
    }


_SIMPLICITY_RANK = {
    "max_score": 0,
    "lexical_topk": 1,
    "lexical_top1": 2,
    "score_margin": 3,
    "score_concentration": 4,
    "combined": 5,
}


def select_strategy(
    grid_rows: list[dict[str, Any]],
    *,
    min_answerable_retention: float = 0.85,
) -> dict[str, Any] | None:
    """Choose a strategy from DEV rows using the milestone priority order.

    The ``max_score`` strategy is excluded from selection: it is the production
    baseline (a single similarity threshold) and the milestone explicitly
    requires it not be selected automatically. Alternatives (margin,
    concentration, lexical, combined) are candidates.

    1. Preserve answerable queries: candidate must keep at least
       ``min_answerable_retention`` (default 0.85).
    2. Among survivors pick the highest unsupported detection.
    3. Tie-break toward simpler strategies, then deterministic display name.

    A single-strategy improvement over the baseline (unsupported detection 0.0)
    is required; if nothing clears the retention floor with a real detection
    gain, ``None`` is returned (do not force a bad heuristic into production).
    """
    qualified = [
        row
        for row in grid_rows
        if row["name"] != "max_score"
        and row["answerable_retention"] >= min_answerable_retention
        and row["unsupported_detection"] > 0.0
    ]
    if not qualified:
        return None
    qualified.sort(
        key=lambda row: (
            -row["unsupported_detection"],
            -row["balanced_accuracy"],
            _SIMPLICITY_RANK.get(row["name"], 99),
            row["strategy"],
        )
    )
    return qualified[0]


def integration_verdict(
    selected_metrics: dict[str, Any] | None,
    *,
    min_holdout_retention: float = 0.85,
    min_holdout_detection: float = 0.1,
) -> dict[str, Any]:
    """Decide whether production integration is justified from the HOLDOUT.

    The DEV-selected strategy must also survive holdout: answerable retention
    must remain at or above ``min_holdout_retention`` and unsupported detection
    must improve over the 0.0 baseline. A collapse on holdout means the DEV
    tuning overfit and no heuristic should be forced into production.
    """
    if selected_metrics is None:
        return {
            "integrate": False,
            "reason": "no_strategy_selected_on_dev",
            "note": "No deterministic strategy cleared the DEV bar; no heuristic was selected.",
        }
    holdout = selected_metrics.get("split:holdout", {})
    retention = holdout.get("answerable_retention", 0.0)
    detection = holdout.get("unsupported_detection", 0.0)
    if retention >= min_holdout_retention and detection > min_holdout_detection:
        return {
            "integrate": True,
            "reason": "holdout_confirmed",
            "note": (
                "Strategy preserves answerable queries on holdout and improves "
                "unsupported detection over the 0.0 baseline."
            ),
        }
    if detection <= min_holdout_detection:
        return {
            "integrate": False,
            "reason": "holdout_detection_collapse",
            "note": (
                "DEV tuning overfit: unsupported detection collapsed on the "
                "holdout split. No heuristic was forced into production."
            ),
        }
    return {
        "integrate": False,
        "reason": "holdout_retention_loss",
        "note": (
            "Holdout answerable retention fell below the acceptable floor. "
            "No heuristic was forced into production."
        ),
    }
