"""Report serialization: deterministic JSON, human-readable Markdown, console summary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

CATEGORY_LABELS = {
    "private_direct": "Private direct lookup",
    "private_paraphrase": "Private semantic paraphrase",
    "private_multi_chunk": "Private multi-chunk",
    "reference_direct": "Reference direct lookup",
    "reference_paraphrase": "Reference semantic paraphrase",
    "combined_private_winner": "Combined private winner",
    "combined_reference_winner": "Combined reference winner",
    "combined_multi_source": "Combined multi-source",
    "cross_space_decoy": "Same-user cross-space decoy",
    "cross_user_decoy": "Cross-user decoy",
    "unanswerable_private": "Unanswerable private",
    "unanswerable_reference": "Unanswerable reference",
    "unanswerable_combined": "Unanswerable combined",
    "hard_negative": "Hard negative",
    "semantic_decoy": "Semantic decoy",
}


def _round_metrics(metrics: dict[str, Any], group_key: str | None = None) -> dict[str, Any]:
    return metrics


def build_json_report(
    *,
    dataset_version: str,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimension: int,
    top_k: int,
    threshold: float,
    corpus_counts: dict[str, int],
    evaluation,
    top_k_sweep: list[dict[str, Any]] | None,
    threshold_sweep: list[dict[str, Any]] | None,
    runtime_seconds: float | None,
    git_commit: str | None,
) -> dict[str, Any]:
    queries = []
    for result in sorted(evaluation.results, key=lambda r: r.id):
        queries.append(
            {
                "id": result.id,
                "scope": result.scope,
                "category": result.category,
                "space": result.space,
                "answerable": result.answerable,
                "question": result.question,
                "first_relevant_rank": result.first_relevant_rank,
                "retrieval_count": result.retrieval_count,
                "retrieved": [
                    {
                        "document": doc,
                        "source_kind": kind,
                        "score": score,
                        "relevant": relevant,
                        "forbidden": forbidden,
                    }
                    for doc, kind, score, relevant, forbidden in zip(
                        result.candidate_documents,
                        result.candidate_kinds,
                        result.candidate_scores,
                        result.candidate_relevant,
                        result.candidate_forbidden,
                        strict=True,
                    )
                ],
                "forbidden_retrieved": result.forbidden_retrieved,
                "scope_violations": result.scope_violations,
            }
        )
    return {
        "benchmark": {
            "dataset_version": dataset_version,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
            "top_k": top_k,
            "similarity_threshold": threshold,
            "query_count": len(evaluation.results),
            "corpus": corpus_counts,
            "runtime_seconds": round(runtime_seconds, 2) if runtime_seconds is not None else None,
            "git_commit": git_commit,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        "metrics": evaluation.metrics,
        "top_k_sweep": top_k_sweep or [],
        "threshold_sweep": threshold_sweep or [],
        "queries": queries,
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _metric_rows(metrics: dict[str, Any]) -> list[tuple[str, str]]:
    rows = [
        ("Hit@1", _fmt(metrics.get("hit_at_1"))),
        ("Hit@3", _fmt(metrics.get("hit_at_3"))),
        ("Hit@5", _fmt(metrics.get("hit_at_5"))),
        ("Recall@1", _fmt(metrics.get("recall_at_1"))),
        ("Recall@3", _fmt(metrics.get("recall_at_3"))),
        ("Recall@5", _fmt(metrics.get("recall_at_5"))),
        ("MRR", _fmt(metrics.get("mrr"))),
        ("Document Hit@5", _fmt(metrics.get("document_hit_at_5"))),
        ("Unanswerable rejection", _fmt(metrics.get("unanswerable_rejection_rate"))),
        ("Unanswerable false positives", str(metrics.get("unanswerable_false_positives", 0))),
        ("Avg candidates (answerable)", _fmt(metrics.get("average_candidate_count_answerable"))),
        (
            "Avg candidates (unanswerable)",
            _fmt(metrics.get("average_candidate_count_unanswerable")),
        ),
    ]
    return rows


def render_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    metrics = report["metrics"]
    lines: list[str] = []
    lines.append("# DocuMind Retrieval Benchmark")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Dataset version: {benchmark['dataset_version']}")
    lines.append(f"- Embedding provider: {benchmark['embedding_provider']}")
    lines.append(f"- Embedding model: {benchmark['embedding_model']}")
    lines.append(f"- Embedding dimension: {benchmark['embedding_dimension']}")
    lines.append(f"- top_k: {benchmark['top_k']}")
    lines.append(f"- similarity threshold: {benchmark['similarity_threshold']}")
    lines.append(f"- Queries: {benchmark['query_count']}")
    corpus = benchmark["corpus"]
    lines.append(
        f"- Corpus: {corpus.get('private_documents', '?')} private docs, "
        f"{corpus.get('reference_documents', '?')} reference docs, "
        f"{corpus.get('chunks', '?')} chunks"
    )
    if benchmark.get("runtime_seconds") is not None:
        lines.append(f"- Runtime: {benchmark['runtime_seconds']}s")
    lines.append("")
    lines.append("## Overall")
    lines.append("")
    lines.extend(_markdown_table(_metric_rows(metrics.get("overall", {}))))
    lines.append("")
    lines.append("## Scope breakdown")
    lines.append("")
    for scope in ("private", "reference", "combined"):
        scope_metrics = metrics.get(scope, {})
        lines.append(f"### {scope.capitalize()}")
        lines.append("")
        lines.extend(_markdown_table(_metric_rows(scope_metrics)))
        lines.append("")
    lines.append("## Unanswerable queries")
    lines.append("")
    unanswerable = metrics.get("overall", {})
    lines.append(f"- Rejection rate: {_fmt(unanswerable.get('unanswerable_rejection_rate'))}")
    lines.append(f"- False positives: {unanswerable.get('unanswerable_false_positives', 0)}")
    lines.append("")
    lines.append("## Security isolation")
    lines.append("")
    security = metrics.get("security", {})
    lines.append(
        f"- Cross-user leakage: {security.get('cross_user_leaked', '?')}/"
        f"{security.get('cross_user_tested', '?')}"
    )
    lines.append(
        f"- Cross-space leakage: {security.get('cross_space_leaked', '?')}/"
        f"{security.get('cross_space_tested', '?')}"
    )
    lines.append(f"- Scope violations: {len(security.get('scope_violations', []))}")
    lines.append(f"- Combined source coverage: {_fmt(security.get('combined_source_coverage'))}")
    lines.append("")
    lines.append("## Query-category breakdown")
    lines.append("")
    lines.append("| Category | Queries | Hit@1 | Hit@3 | Hit@5 | MRR |")
    lines.append("|---|---|---|---|---|---|")
    for key, label in sorted(CATEGORY_LABELS.items()):
        category_metrics = metrics.get(f"category:{key}", {})
        if not category_metrics:
            continue
        lines.append(
            f"| {label} | {category_metrics.get('query_count', 0)} | "
            f"{_fmt(category_metrics.get('hit_at_1'))} | "
            f"{_fmt(category_metrics.get('hit_at_3'))} | "
            f"{_fmt(category_metrics.get('hit_at_5'))} | "
            f"{_fmt(category_metrics.get('mrr'))} |"
        )
    lines.append("")

    if report.get("top_k_sweep"):
        lines.append("## top_k sweep")
        lines.append("")
        lines.append(
            "Metrics labelled @k are evaluated within that row's context window "
            "(Hit@k / Recall@k use k = that row's top_k)."
        )
        lines.append("")
        lines.append("| top_k | Hit@k | Recall@k | MRR | Rejection | Avg candidates |")
        lines.append("|---|---|---|---|---|---|")
        for row in report["top_k_sweep"]:
            lines.append(
                f"| {row['top_k']} | {_fmt(row.get('hit_at_k'))} | "
                f"{_fmt(row.get('recall_at_k'))} | "
                f"{_fmt(row.get('mrr'))} | "
                f"{_fmt(row.get('unanswerable_rejection_rate'))} | "
                f"{_fmt(row.get('average_candidate_count_answerable'))} |"
            )
        lines.append("")

    if report.get("threshold_sweep"):
        lines.append("## similarity-threshold sweep")
        lines.append("")
        lines.append(
            "Hit@k / Recall@k use k = the sweep's fixed top_k; rejection is the "
            "unanswerable rejection rate at that threshold."
        )
        lines.append("")
        lines.append("| Threshold | Hit@k | Recall@k | MRR | Rejection | Avg candidates |")
        lines.append("|---|---|---|---|---|---|")
        for row in report["threshold_sweep"]:
            lines.append(
                f"| {row['threshold']:.2f} | {_fmt(row.get('hit_at_k'))} | "
                f"{_fmt(row.get('recall_at_k'))} | {_fmt(row.get('mrr'))} | "
                f"{_fmt(row.get('unanswerable_rejection_rate'))} | "
                f"{_fmt(row.get('average_candidate_count_answerable'))} |"
            )
        lines.append("")

    failed = [r for r in report["queries"] if r["answerable"] and r["first_relevant_rank"] is None]
    lines.append("## Failed answerable retrievals")
    lines.append("")
    if not failed:
        lines.append("None.")
    else:
        for query in failed:
            retrieved = (
                ", ".join(f"{item['document']}({item['score']:.3f})" for item in query["retrieved"])
                or "none"
            )
            lines.append(f"- **{query['id']}** ({query['category']}, {query['scope']})")
            lines.append(f"  - Question: {query['question']}")
            lines.append(f"  - Retrieved: {retrieved}")
    lines.append("")

    false_positives = [
        r for r in report["queries"] if not r["answerable"] and r["retrieval_count"] > 0
    ]
    lines.append("## Unanswerable false positives")
    lines.append("")
    if not false_positives:
        lines.append("None.")
    else:
        for query in false_positives:
            retrieved = ", ".join(
                f"{item['document']}({item['source_kind']},{item['score']:.3f})"
                for item in query["retrieved"]
            )
            lines.append(f"- **{query['id']}** ({query['scope']})")
            lines.append(f"  - Question: {query['question']}")
            lines.append(f"  - Retrieved: {retrieved}")
    lines.append("")

    distributions = metrics.get("score_distributions", {})
    lines.append("## Score distributions")
    lines.append("")
    lines.append("| Group | Count | Mean | Min | Max |")
    lines.append("|---|---|---|---|---|")
    for group in ("relevant", "irrelevant", "unanswerable_top"):
        stats = distributions.get(group, {})
        lines.append(
            f"| {group} | {stats.get('count', 0)} | {_fmt(stats.get('mean'))} | "
            f"{_fmt(stats.get('min'))} | {_fmt(stats.get('max'))} |"
        )
    lines.append("")
    lines.append("## Observations")
    lines.append("")
    lines.append(
        "Synthetic benchmark baseline. Results depend on dataset version, embedding model, "
        "threshold, and top_k. Not a measure of production or general RAG quality."
    )
    lines.append("")
    lines.append(
        "Chunking limitation: the v1 corpus largely uses one synthetic chunk per page "
        "(21 chunks across 21 pages), so it does not stress long-page splitting, overlap "
        "boundaries, facts spanning a chunk boundary, or duplicate context from overlap. "
        "It is not a comprehensive chunking-strategy benchmark."
    )
    lines.append("")
    return "\n".join(lines)


def _markdown_table(rows: list[tuple[str, str]]) -> list[str]:
    lines = ["| Metric | Result |", "|---|---|"]
    for name, value in rows:
        lines.append(f"| {name} | {value} |")
    return lines


def print_console_summary(report: dict[str, Any]) -> None:
    benchmark = report["benchmark"]
    metrics = report["metrics"]
    overall = metrics.get("overall", {})
    security = metrics.get("security", {})
    print("DocuMind Retrieval Benchmark")
    print(f"Dataset: v{benchmark['dataset_version']}")
    print(f"Queries: {benchmark['query_count']}")
    print(f"Model: {benchmark['embedding_model']}")
    print(f"top_k: {benchmark['top_k']}")
    print(f"threshold: {benchmark['similarity_threshold']:.2f}")
    print("")
    print("Overall")
    print(f"Hit@1: {_fmt(overall.get('hit_at_1'))}")
    print(f"Hit@3: {_fmt(overall.get('hit_at_3'))}")
    print(f"Hit@5: {_fmt(overall.get('hit_at_5'))}")
    print(f"Recall@1: {_fmt(overall.get('recall_at_1'))}")
    print(f"Recall@3: {_fmt(overall.get('recall_at_3'))}")
    print(f"MRR: {_fmt(overall.get('mrr'))}")
    print("")
    rejected = int(
        (overall.get("unanswerable", 0) or 0) * (overall.get("unanswerable_rejection_rate") or 0)
    )
    print(
        f"Unanswerable rejection: {overall.get('unanswerable_rejection_rate'):.3f} "
        f"({rejected}/{overall.get('unanswerable', 0)})"
    )
    print(
        f"Cross-user leakage: {security.get('cross_user_leaked', 0)}/"
        f"{security.get('cross_user_tested', 0)}"
    )
    print(
        f"Cross-space leakage: {security.get('cross_space_leaked', 0)}/"
        f"{security.get('cross_space_tested', 0)}"
    )


def write_json_report(report: dict[str, Any], path) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, ensure_ascii=False)
