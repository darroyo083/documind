"""Retrieval-only preflight for the frozen v2 verifier holdout.

The preflight runs real production retrieval over the v2 corpus (local
FastEmbed, isolated PostgreSQL) and decides whether v2 may be frozen. It never
invokes any verifier -- mock or external -- so it performs zero verifier calls.
Mock/metric-less retrieval eligibility is the only thing evaluated here.

Eligibility rules (all must hold before freezing):

- every answerable query has ALL its expected evidence available within top_k=5
- cross-user leakage == 0
- cross-space leakage == 0
- the combined multi-source answerable case has both source kinds present

This module does not tune retrieval, top_k, threshold, chunking, or any other
production configuration. Generated reports are gitignored.
"""

from __future__ import annotations

import json
from typing import Any

from app.evaluation import metrics
from app.evaluation.runner import Corpus, QueryResult
from app.evaluation.verifier_dataset import V2_QUERY_COUNT

_RUN_MODE = "retrieval_preflight"


def query_eligibility(corpus: Corpus, result: QueryResult) -> dict[str, Any]:
    """Eligibility detail for one query (no verifier, no mock semantics)."""
    expected = set(result.expected_chunks)
    covered: set[str] = set()
    for chunk in result.candidate_chunks:
        covered.update(corpus.chunk_to_pages.get(chunk.chunk_id, []))
    missing = expected - covered
    return {
        "query_id": result.id,
        "scope": result.scope,
        "answerable": result.answerable,
        "category": result.category,
        "question": result.question,
        "expected_chunks": list(result.expected_chunks),
        "expected_ranks": list(result.relevant_ranks),
        "retrieval_count": result.retrieval_count,
        "top_score": max(result.candidate_scores) if result.candidate_scores else None,
        "hit_at_1": bool(metrics.hit_at_k(result.relevant_ranks, 1)),
        "hit_at_3": bool(metrics.hit_at_k(result.relevant_ranks, 3)),
        "hit_at_5": bool(metrics.hit_at_k(result.relevant_ranks, 5)),
        "all_expected_covered": not missing,
        "missing_expected_chunks": sorted(missing),
        "candidate_documents": list(result.candidate_documents),
        "candidate_kinds": list(result.candidate_kinds),
        "top_candidate_document": result.candidate_documents[0]
        if result.candidate_documents
        else None,
        "top_candidate_kind": result.candidate_kinds[0] if result.candidate_kinds else None,
    }


def compute_eligibility(corpus: Corpus, results: list[QueryResult]) -> dict[str, Any]:
    """Aggregate retrieval eligibility for the v2 holdout."""
    rows = [query_eligibility(corpus, result) for result in sorted(results, key=lambda r: r.id)]
    answerable = [row for row in rows if row["answerable"]]
    unsupported = [row for row in rows if not row["answerable"]]

    hit1 = sum(1 for row in answerable if row["hit_at_1"]) / len(answerable) if answerable else 0.0
    hit3 = sum(1 for row in answerable if row["hit_at_3"]) / len(answerable) if answerable else 0.0
    hit5 = sum(1 for row in answerable if row["hit_at_5"]) / len(answerable) if answerable else 0.0
    all_covered = sum(1 for row in answerable if row["all_expected_covered"])
    unsupported_with_candidates = sum(1 for row in unsupported if row["retrieval_count"] > 0)

    candidate_counts = [r.retrieval_count for r in results]
    answerable_top_scores = [row["top_score"] for row in answerable if row["top_score"] is not None]
    unsupported_top_scores = [
        row["top_score"] for row in unsupported if row["top_score"] is not None
    ]

    multi_source = [row for row in rows if set(row["candidate_kinds"]) == {"private", "reference"}]
    combined_coverage = sum(
        1
        for r in results
        if set(r.required_source_kinds) == {"private", "reference"}
        and set(r.source_kinds_present) == {"private", "reference"}
    )
    combined_required = sum(
        1 for r in results if set(r.required_source_kinds) == {"private", "reference"}
    )

    security = {
        "cross_user_tested": sum(1 for r in results if r.has_cross_user_forbidden),
        "cross_user_leaked": sum(
            1 for r in results if r.has_cross_user_forbidden and r.forbidden_retrieved
        ),
        "cross_space_tested": sum(1 for r in results if r.has_cross_space_forbidden),
        "cross_space_leaked": sum(
            1 for r in results if r.has_cross_space_forbidden and r.forbidden_retrieved
        ),
        "scope_violations": [r.id for r in results if r.scope_violations],
    }

    eligible = (
        all_covered == len(answerable)
        and security["cross_user_leaked"] == 0
        and security["cross_space_leaked"] == 0
        and not security["scope_violations"]
        and combined_coverage == combined_required
    )

    return {
        "run_mode": _RUN_MODE,
        "query_count": len(results),
        "answerable_count": len(answerable),
        "unsupported_count": len(unsupported),
        "answerable_hit_at_1": round(hit1, 4),
        "answerable_hit_at_3": round(hit3, 4),
        "answerable_hit_at_5": round(hit5, 4),
        "answerable_with_all_expected_in_top5": all_covered,
        "unsupported_with_candidates": unsupported_with_candidates,
        "average_candidate_count": round(sum(candidate_counts) / len(candidate_counts), 4)
        if candidate_counts
        else 0.0,
        "answerable_top_score_distribution": metrics.score_statistics(answerable_top_scores),
        "unsupported_top_score_distribution": metrics.score_statistics(unsupported_top_scores),
        "combined_required": combined_required,
        "combined_source_coverage": round(combined_coverage / combined_required, 4)
        if combined_required
        else 0.0,
        "multi_source_candidate_kinds_matched": len(multi_source),
        "security": security,
        "eligible_to_freeze": eligible,
        "queries": rows,
    }


def build_preflight_json_report(
    *,
    dataset_path: str,
    dataset_canonical_sha256: str,
    dataset_version: str,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimension: int,
    top_k: int,
    threshold: float,
    corpus_counts: dict[str, int],
    runtime_seconds: float | None,
    git_commit: str | None,
    eligibility: dict[str, Any],
) -> dict[str, Any]:
    """Machine-readable retrieval-preflight report (clearly labeled, never semantic)."""
    return {
        "benchmark": {
            "kind": "verifier_v2_retrieval_preflight",
            "run_mode": _RUN_MODE,
            "dataset_version": dataset_version,
            "dataset_path": dataset_path,
            "dataset_canonical_sha256": dataset_canonical_sha256,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
            "top_k": top_k,
            "similarity_threshold": threshold,
            "corpus": corpus_counts,
            "runtime_seconds": round(runtime_seconds, 2) if runtime_seconds is not None else None,
            "git_commit": git_commit,
        },
        "eligibility": eligibility,
        "note": (
            "Retrieval-only preflight for the frozen v2 holdout. No verifier "
            "(mock or external) was invoked; these results say nothing about "
            "verifier quality. They only certify that v2 retrieval ground truth "
            "is reachable under the frozen benchmark configuration."
        ),
    }


def render_preflight_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    eligibility = report["eligibility"]
    security = eligibility["security"]
    lines: list[str] = []
    lines.append("# DocuMind Verifier V2 Retrieval Preflight (PoC 3F-B)")
    lines.append("")
    lines.append("## Run configuration")
    lines.append("")
    lines.append(f"- Dataset: {benchmark['dataset_path']}")
    lines.append(f"- Dataset version: {benchmark['dataset_version']}")
    lines.append(f"- Dataset canonical SHA-256: {benchmark['dataset_canonical_sha256']}")
    lines.append(f"- Embedding provider: {benchmark['embedding_provider']}")
    lines.append(f"- Embedding model: {benchmark['embedding_model']}")
    lines.append(f"- Embedding dimension: {benchmark['embedding_dimension']}")
    lines.append(f"- top_k: {benchmark['top_k']}")
    lines.append(f"- similarity threshold: {benchmark['similarity_threshold']}")
    lines.append(
        f"- Corpus: {benchmark['corpus'].get('private_documents')} private docs, "
        f"{benchmark['corpus'].get('reference_documents')} reference docs, "
        f"{benchmark['corpus'].get('chunks')} chunks"
    )
    if benchmark.get("runtime_seconds") is not None:
        lines.append(f"- Runtime: {benchmark['runtime_seconds']}s")
    lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append(report["note"])
    lines.append("")
    lines.append("## Eligibility")
    lines.append("")
    lines.append(f"- eligible_to_freeze: **{eligibility['eligible_to_freeze']}**")
    lines.append(f"- total queries: {eligibility['query_count']} (expected {V2_QUERY_COUNT})")
    lines.append(
        f"- answerable: {eligibility['answerable_count']} / "
        f"unsupported: {eligibility['unsupported_count']}"
    )
    lines.append(f"- answerable Hit@1: {eligibility['answerable_hit_at_1']}")
    lines.append(f"- answerable Hit@3: {eligibility['answerable_hit_at_3']}")
    lines.append(f"- answerable Hit@5: {eligibility['answerable_hit_at_5']}")
    lines.append(
        f"- answerable with ALL expected evidence in top5: "
        f"{eligibility['answerable_with_all_expected_in_top5']}"
    )
    lines.append(f"- unsupported with >=1 candidate: {eligibility['unsupported_with_candidates']}")
    lines.append(f"- average candidate count: {eligibility['average_candidate_count']}")
    lines.append(
        f"- combined required: {eligibility['combined_required']}, "
        f"combined source coverage: {eligibility['combined_source_coverage']}"
    )
    lines.append(
        f"- cross-user leakage: {security['cross_user_leaked']} / "
        f"tested {security['cross_user_tested']}"
    )
    lines.append(
        f"- cross-space leakage: {security['cross_space_leaked']} / "
        f"tested {security['cross_space_tested']}"
    )
    lines.append(f"- scope violations: {security['scope_violations']}")
    lines.append("")
    lines.append("## Per query")
    lines.append("")
    lines.append(
        "| id | scope | answerable | candidates | top_score | hit@1 | hit@3 | "
        "hit@5 | all_expected_covered | top candidate |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for row in eligibility["queries"]:
        lines.append(
            f"| {row['query_id']} | {row['scope']} | {row['answerable']} | "
            f"{row['retrieval_count']} | {row['top_score']} | {row['hit_at_1']} | "
            f"{row['hit_at_3']} | {row['hit_at_5']} | {row['all_expected_covered']} | "
            f"{row['top_candidate_document']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_preflight_report(report: dict[str, Any], path) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, ensure_ascii=False)
