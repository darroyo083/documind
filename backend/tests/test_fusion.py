import pytest

from app.application.fusion import (
    reciprocal_rank_fusion,
    suppress_redundant_candidates,
)
from app.domain.rag import RetrievedChunk


def _chunk(
    chunk_id: str,
    content: str = "content",
    score: float = 0.5,
    document_id: str = "doc-1",
    page_number: int = 1,
    chunk_index: int = 0,
    source_kind: str = "private",
) -> RetrievedChunk:
    return RetrievedChunk(
        source_id=f"{source_kind}:{chunk_id}",
        source_kind=source_kind,
        document_id=document_id,
        document_name="file.pdf",
        page_number=page_number,
        chunk_id=chunk_id,
        content=content,
        score=score,
        chunk_index=chunk_index,
    )


def test_rrf_boosts_candidates_present_in_multiple_channels():
    a = _chunk("a", score=0.9)
    b = _chunk("b", score=0.8)
    c = _chunk("c", score=0.7)

    fused = reciprocal_rank_fusion([[a, b], [c, a]], k=60)

    assert [chunk.chunk_id for chunk in fused] == ["a", "c", "b"]


def test_rrf_is_deterministic_on_ties():
    a = _chunk("a")
    b = _chunk("b")

    first = reciprocal_rank_fusion([[a, b]], k=60)
    second = reciprocal_rank_fusion([[a, b]], k=60)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]


def test_rrf_keeps_channel_native_scores_untouched():
    a = _chunk("a", score=0.42)

    fused = reciprocal_rank_fusion([[a]], k=60)

    assert fused[0].score == 0.42


def test_rrf_rejects_non_positive_k():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[_chunk("a")]], k=0)


def test_suppression_removes_contained_overlap_duplicate_same_document():
    base = "The termination clause requires thirty days written notice by registered mail"
    full = _chunk("full", content=f"{base} plus additional detail sentence here", chunk_index=0)
    duplicate = _chunk("dup", content=f"{base} thirty days written notice", chunk_index=1)

    kept = suppress_redundant_candidates([full, duplicate])

    assert [chunk.chunk_id for chunk in kept] == ["full"]


def test_suppression_preserves_cross_document_duplicates():
    text = "Identical evidence appearing in two separate documents must both survive suppression"
    first = _chunk("first", content=text, document_id="doc-1")
    second = _chunk("second", content=text, document_id="doc-2")

    kept = suppress_redundant_candidates([first, second])

    assert {chunk.chunk_id for chunk in kept} == {"first", "second"}


def test_suppression_preserves_distinct_content():
    alpha = _chunk("alpha", content="Quarterly revenue grew by twelve percent year over year")
    beta = _chunk("beta", content="Headcount plans for the next fiscal year remain unchanged")

    kept = suppress_redundant_candidates([alpha, beta])

    assert len(kept) == 2


def test_suppression_limit_bounds_results():
    chunks = [
        _chunk(f"chunk-{index}", content=f"unique content {index}", chunk_index=index)
        for index in range(6)
    ]

    kept = suppress_redundant_candidates(chunks, limit=3)

    assert len(kept) == 3


def test_suppression_rejects_invalid_threshold():
    with pytest.raises(ValueError):
        suppress_redundant_candidates([_chunk("a")], containment_threshold=0)
