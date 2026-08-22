"""Candidate fusion and redundancy suppression for hybrid retrieval.

Hybrid retrieval produces one ranked list per candidate channel (semantic
similarity, lexical relevance). ``reciprocal_rank_fusion`` merges ranked lists
without requiring comparable raw scores: a candidate's fused score depends only
on its rank position in each channel. The chunk's own ``score`` attribute keeps
its channel-native meaning (cosine similarity); fusion ordering is separate.

``suppress_redundant_candidates`` drops lower-ranked chunks whose text is
almost fully contained in an already-selected chunk of the same document.
Fixed-window chunking with overlap legitimately produces such near-duplicates;
spending two context slots on the same passage wastes evidence budget without
adding information.
"""

from __future__ import annotations

import re

from app.domain.rag import RetrievedChunk

_DEFAULT_RRF_K = 60
_NORMALIZATION_PATTERN = re.compile(r"[^a-z0-9]+")


def _normalize_for_containment(text: str) -> str:
    return _NORMALIZATION_PATTERN.sub(" ", text.lower()).strip()


def _containment(candidate: str, selected: str) -> float:
    """Fraction of candidate's words already covered by the selected text."""
    candidate_tokens = set(_normalize_for_containment(candidate).split())
    if not candidate_tokens:
        return 0.0
    selected_tokens = set(_normalize_for_containment(selected).split())
    covered = sum(1 for token in candidate_tokens if token in selected_tokens)
    return covered / len(candidate_tokens)


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    k: int = _DEFAULT_RRF_K,
    weights: list[float] | None = None,
) -> list[RetrievedChunk]:
    """Merge ranked candidate lists with (optionally weighted) Reciprocal Rank Fusion.

    Fused score = sum over lists of ``weight_i / (k + rank_i)``, ranks starting
    at 1. A candidate absent from a channel contributes nothing for that
    channel. Weights let stronger channels dominate ordering: with the default
    embedding model semantic ranking is typically most reliable, so the lexical
    channel usually runs below weight 1.0 (see ``settings.retrieval_lexical_weight``).
    """
    if k <= 0:
        raise ValueError("RRF constant k must be positive")
    if weights is not None and len(weights) != len(ranked_lists):
        raise ValueError("weights must match the number of ranked lists")
    if weights is not None and any(weight <= 0 for weight in weights):
        raise ValueError("channel weights must be positive")

    channel_weights = weights if weights is not None else [1.0] * len(ranked_lists)

    fused_scores: dict[str, float] = {}
    best_native_score: dict[str, float] = {}
    first_channel: dict[str, int] = {}
    candidates: dict[str, RetrievedChunk] = {}

    for channel_index, ranked in enumerate(ranked_lists):
        weight = channel_weights[channel_index]
        for rank, candidate in enumerate(ranked, start=1):
            key = candidate.chunk_id
            fused_scores[key] = fused_scores.get(key, 0.0) + weight / (k + rank)
            candidates[key] = candidate
            current_best = best_native_score.get(key)
            if current_best is None or candidate.score > current_best:
                best_native_score[key] = candidate.score
            if key not in first_channel:
                first_channel[key] = channel_index

    ordered_keys = sorted(
        fused_scores,
        key=lambda key: (
            -fused_scores[key],
            first_channel[key],
            -best_native_score[key],
            candidates[key].document_id,
            candidates[key].page_number,
            candidates[key].chunk_index,
        ),
    )
    return [candidates[key] for key in ordered_keys]


def suppress_redundant_candidates(
    candidates: list[RetrievedChunk],
    *,
    containment_threshold: float = 0.85,
    limit: int | None = None,
) -> list[RetrievedChunk]:
    """Drop later-ranked chunks nearly contained in an accepted same-document chunk.

    The first occurrence of a passage wins; subsequent chunks from the same
    document that restate it (typical overlap windows) are suppressed. Chunks
    from other documents are never compared against each other, so genuinely
    duplicated evidence across documents is preserved for contradiction-aware
    answering.
    """
    if not 0 < containment_threshold <= 1:
        raise ValueError("containment_threshold must be in (0, 1]")

    kept: list[RetrievedChunk] = []
    accepted_by_document: dict[str, list[str]] = {}
    for candidate in candidates:
        document_key = f"{candidate.source_kind}:{candidate.document_id}"
        contents = accepted_by_document.setdefault(document_key, [])
        if any(
            _containment(candidate.content, content) >= containment_threshold
            for content in contents
        ):
            continue
        kept.append(candidate)
        contents.append(candidate.content)
        if limit is not None and len(kept) >= limit:
            break
    return kept
