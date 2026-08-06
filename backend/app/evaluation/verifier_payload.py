"""Build verifier-safe evidence payloads from production retrieval output.

Each payload item carries only the metadata needed for grounding a decision:
source id, source kind, document name, page number, excerpt/content, and
retrieval score.

It intentionally omits everything a verifier must never see: hidden ground
truth, answerable flags, expected relevant chunks, semantic fixture ids,
evaluation splits, other users' documents, web results, and extra database
context.

Evidence payloads are constructed only from the candidates that production
retrieval already authorized for the requesting user/space.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from app.domain.rag import RetrievedChunk
from app.evaluation.runner import QueryResult
from app.evaluation.verifier import EvidenceItem


def evidence_item_from_chunk(chunk: RetrievedChunk) -> EvidenceItem:
    """Convert one production-retrieved candidate into a verifier-safe item."""
    return EvidenceItem(
        source_id=chunk.source_id,
        source_kind=chunk.source_kind,
        document_name=chunk.document_name,
        page_number=chunk.page_number,
        content=chunk.content,
        score=round(float(chunk.score), 4),
    )


def evidence_items_from_chunks(chunks: Sequence[RetrievedChunk]) -> list[EvidenceItem]:
    """Convert the retrieved, authorized candidates into the evidence payload."""
    return [evidence_item_from_chunk(chunk) for chunk in chunks]


def build_evidence_items(result: QueryResult) -> list[EvidenceItem]:
    """Build the evidence payload for one retrieval result.

    Prefers the retained production ``RetrievedChunk`` objects. For hand-built
    ``QueryResult`` fixtures (tests) that did not retain chunks, it falls back
    to the parallel candidate columns with synthetic source ids so the
    pipeline, validation, and metrics remain exercisable offline.
    """
    if result.candidate_chunks:
        return evidence_items_from_chunks(result.candidate_chunks)
    return _fallback_from_columns(result)


def _fallback_from_columns(result: QueryResult) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for index, (doc, kind, score, content) in enumerate(
        zip(
            result.candidate_documents,
            result.candidate_kinds,
            result.candidate_scores,
            result.candidate_contents,
            strict=True,
        )
    ):
        items.append(
            EvidenceItem(
                source_id=f"private:chunk-{index}",
                source_kind=kind,
                document_name=doc,
                page_number=1,
                content=content,
                score=score,
            )
        )
    return items


def evidence_item_to_dict(item: EvidenceItem) -> dict[str, Any]:
    """Serialize one evidence item (used by prompt/report rendering)."""
    return asdict(item)
