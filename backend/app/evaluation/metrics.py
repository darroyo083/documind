"""Pure retrieval metrics.

Higher score means more similar (score = 1 - cosine_distance). Candidates are
ranked from best (rank 1) to worst. These functions have no I/O and are fully
deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence


def hit_at_k(relevant_ranks: Sequence[int], k: int) -> int:
    """1 if any relevant chunk appears at rank <= k, otherwise 0."""
    return 1 if any(rank <= k for rank in relevant_ranks) else 0


def recall_at_k(relevant_ranks: Sequence[int], k: int, total_relevant: int) -> float:
    """Proportion of relevant chunks retrieved within top k."""
    if total_relevant <= 0:
        return 0.0
    retrieved = sum(1 for rank in relevant_ranks if rank <= k)
    return retrieved / total_relevant


def mean_reciprocal_rank(relevant_ranks: Sequence[int]) -> float:
    """1 / rank of the first relevant result; 0 if none retrieved."""
    if not relevant_ranks:
        return 0.0
    return 1.0 / relevant_ranks[0]


def mean_relevant_rank(relevant_ranks: Sequence[int]) -> float | None:
    """Average rank of the first relevant result among successful queries."""
    if not relevant_ranks:
        return None
    return float(relevant_ranks[0])


def document_hit_at_k(relevant_document_ranks: Sequence[int], k: int) -> int:
    """1 if the correct document appears within top k (document-level)."""
    return 1 if any(rank <= k for rank in relevant_document_ranks) else 0


def unanswerable_rejection_rate(empty_retrievals: Sequence[bool]) -> float:
    """Fraction of unanswerable queries that returned zero candidates."""
    if not empty_retrievals:
        return 0.0
    return sum(1 for empty in empty_retrievals if empty) / len(empty_retrievals)


def leakage_rate(leaked: Sequence[bool]) -> float:
    """Fraction of queries in which a forbidden candidate appeared."""
    if not leaked:
        return 0.0
    return sum(1 for value in leaked if value) / len(leaked)


def combined_source_coverage(
    top_k_source_kinds: Sequence[set[str]],
    required_kinds: set[str],
) -> float:
    """Fraction of multi-source queries whose top K contains all required source kinds."""
    total = len(top_k_source_kinds)
    if total == 0:
        return 0.0
    covered = sum(1 for kinds in top_k_source_kinds if required_kinds.issubset(kinds))
    return covered / total


def score_statistics(scores: Sequence[float]) -> dict[str, float | int | None]:
    """count/mean/min/max descriptive statistics for a score list."""
    if not scores:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(scores),
        "mean": round(sum(scores) / len(scores), 4),
        "min": round(min(scores), 4),
        "max": round(max(scores), 4),
    }
