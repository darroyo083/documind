"""Report serialization for evidence-sufficiency experiments.

Deterministic JSON and human-readable Markdown. Runtime reports are written to
the gitignored evaluation results directory and are never committed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

_METRIC_KEYS = (
    "answerable_retention",
    "unsupported_detection",
    "supported_precision",
    "unsupported_precision",
    "false_support_rate",
    "false_rejection_rate",
    "balanced_accuracy",
    "accuracy",
)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _metric_rows(metrics: dict[str, Any]) -> list[tuple[str, str]]:
    rows = []
    for key in _METRIC_KEYS:
        if key in metrics:
            label = key.replace("_", " ").title()
            rows.append((label, _fmt(metrics[key])))
    return rows


def build_sufficiency_json_report(
    *,
    dataset_version: str,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimension: int,
    top_k: int,
    threshold: float,
    baseline: dict[str, Any],
    grid_search: list[dict[str, Any]],
    feature_diagnostics: dict[str, Any],
    selected: dict[str, Any] | None,
    verdict: dict[str, Any],
    corpus_counts: dict[str, int],
    runtime_seconds: float | None,
    git_commit: str | None,
) -> dict[str, Any]:
    """Assemble the machine-readable sufficiency report.

    ``baseline`` is the unselected max-score reproduction at the production
    threshold. ``grid_search`` are DEV-only tuning rows (candidates are never
    evaluated on HOLDOUT). ``selected`` is the frozen chosen strategy config;
    its dev/holdout/overall metrics come from evaluating only that config after
    selection. ``verdict`` records the production-integration decision derived
    from the holdout result.
    """
    return {
        "benchmark": {
            "dataset_version": dataset_version,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
            "top_k": top_k,
            "similarity_threshold": threshold,
            "corpus": corpus_counts,
            "runtime_seconds": round(runtime_seconds, 2) if runtime_seconds is not None else None,
            "git_commit": git_commit,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        "baseline": baseline,
        "grid_search_dev": grid_search,
        "feature_diagnostics": feature_diagnostics,
        "selected_strategy": selected,
        "integration_verdict": verdict,
    }


def _strategy_summary_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Strategy | Retention | Detection | BalAcc | False rej | False sup |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['strategy']} | {_fmt(row.get('answerable_retention'))} | "
            f"{_fmt(row.get('unsupported_detection'))} | "
            f"{_fmt(row.get('balanced_accuracy'))} | "
            f"{_fmt(row.get('false_rejection_rate'))} | "
            f"{_fmt(row.get('false_support_rate'))} |"
        )
    return lines


def _markdown_table(rows: list[tuple[str, str]]) -> list[str]:
    lines = ["| Metric | Result |", "|---|---|"]
    for name, value in rows:
        lines.append(f"| {name} | {value} |")
    return lines


def _render_metrics_group(lines: list[str], metrics: dict[str, Any]) -> None:
    lines.extend(_markdown_table(_metric_rows(metrics)))


def render_sufficiency_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    lines: list[str] = []
    lines.append("# DocuMind Evidence Sufficiency Experiment (PoC 3E)")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Dataset version: {benchmark['dataset_version']}")
    lines.append(f"- Embedding provider: {benchmark['embedding_provider']}")
    lines.append(f"- Embedding model: {benchmark['embedding_model']}")
    lines.append(f"- Embedding dimension: {benchmark['embedding_dimension']}")
    lines.append(f"- top_k: {benchmark['top_k']}")
    lines.append(f"- similarity threshold: {benchmark['similarity_threshold']}")
    corpus = benchmark["corpus"]
    lines.append(
        f"- Corpus: {corpus.get('private_documents', '?')} private docs, "
        f"{corpus.get('reference_documents', '?')} reference docs, "
        f"{corpus.get('chunks', '?')} chunks"
    )
    if benchmark.get("runtime_seconds") is not None:
        lines.append(f"- Runtime: {benchmark['runtime_seconds']}s")
    lines.append("")

    baseline = report.get("baseline", {})
    lines.append("## Baseline classification (production threshold, max-score)")
    lines.append("")
    _render_metrics_group(lines, baseline.get("overall", {}))
    lines.append("")
    lines.append("### Dev")
    lines.append("")
    _render_metrics_group(lines, baseline.get("dev", {}))
    lines.append("")
    lines.append("### Holdout")
    lines.append("")
    _render_metrics_group(lines, baseline.get("holdout", {}))
    lines.append("")

    grid = report.get("grid_search_dev", [])
    lines.append("## DEV strategy comparison")
    lines.append("")
    lines.append(
        "Grid search over the DEV subset only. Candidate configurations are "
        "never evaluated on the HOLDOUT split. Rows sorted by balanced "
        "accuracy, then answerable retention, then unsupported detection."
    )
    lines.append("")
    lines.extend(_strategy_summary_table(grid[:25]))
    if len(grid) > 25:
        lines.append("")
        lines.append(f"({len(grid) - 25} further DEV rows omitted)")
    lines.append("")

    diagnostics = report.get("feature_diagnostics", {})
    if diagnostics:
        lines.append("## Score-feature diagnostics")
        lines.append("")
        lines.append(
            "Mean/min/max of each signal for answerable vs unanswerable queries "
            "(computed before any strategy decision)."
        )
        lines.append("")
        _render_diagnostics(lines, diagnostics)

    selected = report.get("selected_strategy")
    if selected:
        lines.append("## Selected strategy")
        lines.append("")
        lines.append(f"Strategy: `{selected.get('strategy')}`")
        reasons = sorted({o.get("reason", "") for o in selected.get("outcomes", [])})
        lines.append(f"Reason codes: {', '.join(reasons)}")
        lines.append("")
        metrics = selected.get("metrics", {})
        for group in ("overall", "dev", "holdout"):
            lines.append(f"### {group.title()}")
            lines.append("")
            _render_metrics_group(lines, metrics.get(group, {}))
            lines.append("")
        lines.append("### Per scope")
        lines.append("")
        for scope in ("private", "reference", "combined"):
            lines.append(f"#### {scope.capitalize()}")
            lines.append("")
            _render_metrics_group(lines, metrics.get(scope, {}))
            lines.append("")
    else:
        lines.append("## Selected strategy")
        lines.append("")
        lines.append("None selected: deterministic signals did not clear the bar.")
        lines.append("")

    lines.append("## False rejections (answerable but rejected)")
    lines.append("")
    _append_flagged(selected, lines, answerable=True, supported=False)
    lines.append("")
    lines.append("## False supports (unanswerable but accepted)")
    lines.append("")
    _append_flagged(selected, lines, answerable=False, supported=True)
    lines.append("")

    lines.append("## Security")
    lines.append("")
    lines.append(
        "Sufficiency evaluation operates only over server-authorized retrieval "
        "candidates. Cross-user/cross-space invariants are re-checked by the "
        "retrieval benchmark; expected leakage remains 0."
    )
    lines.append("")

    verdict = report.get("integration_verdict", {})
    lines.append("## Integration verdict")
    lines.append("")
    lines.append(f"Integrate: **{verdict.get('integrate', False)}**")
    lines.append(f"Reason: {verdict.get('reason', 'n/a')}")
    lines.append(f"Note: {verdict.get('note', '')}")
    lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    if verdict.get("integrate"):
        lines.append(
            "The selected strategy improves unsupported detection over the "
            "production baseline while keeping answerable retention acceptable, "
            "including on holdout. It is a deterministic, cheap, explainable "
            "evidence-sufficiency decision; it does not prove answer correctness."
        )
    elif selected:
        lines.append(
            "The DEV-selected strategy did not survive holdout: unsupported "
            "detection collapsed (or answerable retention fell) on unseen data. "
            "Deterministic score/lexical signals alone are not sufficient for a "
            "reliable abstention decision on this corpus. No heuristic was "
            "forced into production. The next experiment should evaluate a "
            "dedicated evidence-verification model."
        )
    else:
        lines.append(
            "No deterministic strategy cleared the DEV bar. Deterministic "
            "signals are insufficient; the next experiment should evaluate a "
            "dedicated evidence-verification model. No heuristic was forced "
            "into production."
        )
    lines.append("")
    return "\n".join(lines)


def _append_flagged(
    selected: dict[str, Any] | None,
    lines: list[str],
    *,
    answerable: bool,
    supported: bool,
) -> None:
    if not selected:
        lines.append("None selected.")
        return
    flagged = [
        outcome
        for outcome in selected.get("outcomes", [])
        if outcome["answerable"] is answerable and outcome["supported"] is supported
    ]
    if not flagged:
        lines.append("None.")
        return
    for outcome in sorted(flagged, key=lambda o: o["query_id"]):
        lines.append(f"- **{outcome['query_id']}** ({outcome['split']}, {outcome['category']})")
        lines.append(f"  - Question: {outcome['question']}")
        lines.append(f"  - Reason: {outcome['reason']}")
        signals = outcome["signals"]
        lines.append(
            f"  - top1={_fmt(signals.get('top1'))}, top2={_fmt(signals.get('top2'))}, "
            f"margin={_fmt(signals.get('margin'))}, "
            f"lex_top1={_fmt(signals.get('lexical_coverage_top1'))}, "
            f"lex_topk={_fmt(signals.get('lexical_coverage_topk'))}"
        )


def _render_diagnostics(lines: list[str], diagnostics: dict[str, Any]) -> None:
    signal_labels = {
        "top1": "top1 score",
        "top2": "top2 score",
        "top3": "top3 score",
        "margin": "top1 - top2",
        "mean_top3": "mean top3",
        "mean_top5": "mean top5",
        "top1_minus_mean_rest": "top1 - mean(rest)",
        "lexical_coverage_top1": "lexical coverage top1",
        "lexical_coverage_topk": "lexical coverage topK",
    }
    lines.append("| Signal | Group | Count | Mean | Min | Max |")
    lines.append("|---|---|---|---|---|---|")
    groups = diagnostics.get("groups", {})
    for signal in signal_labels:
        for group_name in ("answerable", "unanswerable"):
            stats = groups.get(signal, {}).get(group_name)
            if not stats:
                continue
            lines.append(
                f"| {signal_labels[signal]} | {group_name} | {stats.get('count', 0)} | "
                f"{_fmt(stats.get('mean'))} | {_fmt(stats.get('min'))} | "
                f"{_fmt(stats.get('max'))} |"
            )
    lines.append("")


def write_json_report(report: dict[str, Any], path) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, ensure_ascii=False)
