import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.errors import ProviderError
from app.domain.rag import EmbeddingProvider
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    KnowledgeSpace,
)

SEARCH_EXCERPT_CHARS = 400
_SEARCH_OVERFETCH_MULTIPLIER = 3


@dataclass(frozen=True)
class GlobalSearchHit:
    chunk_id: str
    document_id: str
    document_name: str
    space_id: str
    space_name: str
    page_number: int
    excerpt: str
    score: float


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("Query must not be empty")
    if len(normalized) > settings.search_max_query_length:
        raise ValueError(
            f"Query must be no longer than {settings.search_max_query_length} characters"
        )
    return normalized


async def search_spaces(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    embedding_provider: EmbeddingProvider,
    space_ids: list[uuid.UUID] | None = None,
    limit: int | None = None,
) -> list[GlobalSearchHit]:
    """Search READY private documents across the user's Spaces.

    One query embedding is computed and reused. Ownership is enforced in the SQL
    WHERE clause (joined to the current user) BEFORE ranking, so unauthorized
    chunks never enter candidate results. ``space_ids`` narrows the search to
    the user's own Spaces (foreign IDs simply match nothing).
    """
    normalized = _normalize_query(query)
    result_limit = limit if limit is not None else settings.search_max_results
    if result_limit < 1 or result_limit > settings.search_max_results:
        raise ValueError(f"limit must be between 1 and {settings.search_max_results}")
    if space_ids is not None and len(space_ids) > settings.search_max_space_ids:
        raise ValueError(f"Too many space filters (max {settings.search_max_space_ids})")

    query_embedding = await embedding_provider.embed_query(normalized)
    if len(query_embedding) != settings.embedding_dimension:
        raise ProviderError("Embedding provider returned an invalid vector shape")

    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    statement = (
        select(DocumentChunk, Document, KnowledgeSpace, (1 - distance).label("score"))
        .join(Document, DocumentChunk.document_id == Document.id)
        .join(KnowledgeSpace, Document.knowledge_space_id == KnowledgeSpace.id)
        .where(
            KnowledgeSpace.user_id == user_id,
            Document.status == DocumentStatus.READY.value,
            distance <= 1 - settings.default_similarity_threshold,
        )
        .order_by(
            distance,
            Document.id,
            DocumentChunk.page_number,
            DocumentChunk.chunk_index,
        )
        .limit(result_limit * _SEARCH_OVERFETCH_MULTIPLIER)
    )
    if space_ids:
        statement = statement.where(KnowledgeSpace.id.in_(space_ids))

    result = await db.execute(statement)
    candidates = result.all()

    seen_pages: set[tuple[str, int]] = set()
    per_document: dict[str, int] = {}
    hits: list[GlobalSearchHit] = []
    for chunk, document, space, score in candidates:
        doc_key = str(document.id)
        page_key = (doc_key, chunk.page_number)
        if page_key in seen_pages:
            continue
        if per_document.get(doc_key, 0) >= settings.search_max_per_document:
            continue
        seen_pages.add(page_key)
        per_document[doc_key] = per_document.get(doc_key, 0) + 1
        hits.append(
            GlobalSearchHit(
                chunk_id=str(chunk.id),
                document_id=doc_key,
                document_name=document.original_filename,
                space_id=str(space.id),
                space_name=space.name,
                page_number=chunk.page_number,
                excerpt=chunk.content[:SEARCH_EXCERPT_CHARS],
                score=float(score),
            )
        )
        if len(hits) >= result_limit:
            break
    return hits
