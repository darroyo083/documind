"""Grounded retrieval over private and reference knowledge.

Two retrieval modes are supported:

* ``vector`` — pure semantic similarity (cosine distance against pgvector).
* ``hybrid`` (default) — semantic similarity fused with PostgreSQL full-text
  relevance (``tsvector`` + GIN index) via Reciprocal Rank Fusion.

Hybrid retrieval closes a documented semantic-only weakness: exact terms,
names, identifiers, and unusual technical vocabulary often rank poorly under
embedding similarity even when a chunk contains them verbatim. Lexical
matching recovers those cases while semantic ranking keeps paraphrases strong.

Every channel enforces identical ownership/status filters in SQL, so neither
mode can surface chunks outside the caller's authorization scope. Fusion
operates on ranks only; each candidate keeps its true cosine similarity as
``score`` for citations and diagnostics.
"""

import logging
import re
import time
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.fusion import reciprocal_rank_fusion, suppress_redundant_candidates
from app.config import settings
from app.domain.errors import ProviderError
from app.domain.rag import (
    AnswerProvider,
    EmbeddingProvider,
    KnowledgeScope,
    RetrievalMode,
    RetrievedChunk,
    SourceKind,
    parse_retrieval_mode,
)
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    KnowledgeSpace,
    ReferenceDocument,
    ReferenceDocumentChunk,
)
from app.observability import log_event, monotonic_ms
from app.schemas.document import AnswerResponse, CitationResponse, SearchResponse

logger = logging.getLogger("documind.retrieval")

_INTERNAL_SOURCE_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:(?:private|reference|chunk):)?"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)


def resolve_top_k(requested: int | None) -> int:
    top_k = requested or settings.default_top_k
    if top_k > settings.retrieval_max_top_k:
        raise ValueError(f"top_k must be no greater than {settings.retrieval_max_top_k}")
    return top_k


async def _fetch_private_vector(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query_embedding: list[float],
    limit: int,
) -> list[RetrievedChunk]:
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    result = await db.execute(
        select(DocumentChunk, Document, (1 - distance).label("score"))
        .join(Document, DocumentChunk.document_id == Document.id)
        .join(KnowledgeSpace, Document.knowledge_space_id == KnowledgeSpace.id)
        .where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.user_id == user_id,
            Document.status == DocumentStatus.READY.value,
            distance <= 1 - settings.default_similarity_threshold,
        )
        .order_by(distance, DocumentChunk.chunk_index)
        .limit(limit)
    )
    return [_chunk_row(row) for row in result.all()]


async def _fetch_reference_vector(
    db: AsyncSession,
    query_embedding: list[float],
    limit: int,
) -> list[RetrievedChunk]:
    distance = ReferenceDocumentChunk.embedding.cosine_distance(query_embedding)
    result = await db.execute(
        select(
            ReferenceDocumentChunk,
            ReferenceDocument,
            (1 - distance).label("score"),
        )
        .join(
            ReferenceDocument,
            ReferenceDocumentChunk.reference_document_id == ReferenceDocument.id,
        )
        .where(
            ReferenceDocument.status == "ready",
            distance <= 1 - settings.default_similarity_threshold,
        )
        .order_by(distance, ReferenceDocumentChunk.chunk_index)
        .limit(limit)
    )
    return [
        RetrievedChunk(
            source_id=f"reference:{chunk.id}",
            source_kind=SourceKind.REFERENCE.value,
            document_id=str(reference_document.id),
            document_name=reference_document.title,
            page_number=chunk.page_number,
            chunk_id=str(chunk.id),
            content=chunk.content,
            score=float(score),
            chunk_index=chunk.chunk_index,
        )
        for chunk, reference_document, score in result.all()
    ]


async def _fetch_private_lexical(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query_embedding: list[float],
    query: str,
    limit: int,
) -> list[RetrievedChunk]:
    """Lexically relevant private chunks under the same ownership filters.

    An empty ``websearch_to_tsquery`` (stop-word-only or blank queries) matches
    no rows, so the lexical channel degrades to zero candidates instead of
    returning arbitrary documents.
    """
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(DocumentChunk.search_vector, tsquery)
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    result = await db.execute(
        select(DocumentChunk, Document, (1 - distance).label("score"))
        .join(Document, DocumentChunk.document_id == Document.id)
        .join(KnowledgeSpace, Document.knowledge_space_id == KnowledgeSpace.id)
        .where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.user_id == user_id,
            Document.status == DocumentStatus.READY.value,
            DocumentChunk.search_vector.op("@@")(tsquery),
        )
        .order_by(rank.desc(), DocumentChunk.chunk_index)
        .limit(limit)
    )
    return [_chunk_row(row) for row in result.all()]


async def _fetch_reference_lexical(
    db: AsyncSession,
    query_embedding: list[float],
    query: str,
    limit: int,
) -> list[RetrievedChunk]:
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(ReferenceDocumentChunk.search_vector, tsquery)
    distance = ReferenceDocumentChunk.embedding.cosine_distance(query_embedding)
    result = await db.execute(
        select(
            ReferenceDocumentChunk,
            ReferenceDocument,
            (1 - distance).label("score"),
        )
        .join(
            ReferenceDocument,
            ReferenceDocumentChunk.reference_document_id == ReferenceDocument.id,
        )
        .where(
            ReferenceDocument.status == "ready",
            ReferenceDocumentChunk.search_vector.op("@@")(tsquery),
        )
        .order_by(rank.desc(), ReferenceDocumentChunk.chunk_index)
        .limit(limit)
    )
    return [
        RetrievedChunk(
            source_id=f"reference:{chunk.id}",
            source_kind=SourceKind.REFERENCE.value,
            document_id=str(reference_document.id),
            document_name=reference_document.title,
            page_number=chunk.page_number,
            chunk_id=str(chunk.id),
            content=chunk.content,
            score=float(score),
            chunk_index=chunk.chunk_index,
        )
        for chunk, reference_document, score in result.all()
    ]


def _chunk_row(row: Any) -> RetrievedChunk:
    chunk, document, score = row
    return RetrievedChunk(
        source_id=f"private:{chunk.id}",
        source_kind=SourceKind.PRIVATE.value,
        document_id=str(document.id),
        document_name=document.original_filename,
        page_number=chunk.page_number,
        chunk_id=str(chunk.id),
        content=chunk.content,
        score=float(score),
        chunk_index=chunk.chunk_index,
    )


def _merge_candidates(
    private_candidates: list[RetrievedChunk],
    reference_candidates: list[RetrievedChunk],
    top_k: int | None,
) -> list[RetrievedChunk]:
    """Merge private + reference candidates, sort globally by score, apply global top_k.

    Tie-breaking is deterministic: score descending, then source kind, document id,
    page number, chunk index. No score boosts or reranking are applied. ``top_k``
    may be ``None`` to keep the full merged ordering (used before diversity
    suppression in hybrid combined-scope retrieval).
    """
    combined = [*private_candidates, *reference_candidates]
    combined.sort(
        key=lambda candidate: (
            -candidate.score,
            candidate.source_kind,
            candidate.document_id,
            candidate.page_number,
            candidate.chunk_index,
            candidate.chunk_id,
        )
    )
    if top_k is None:
        return combined
    return combined[:top_k]


def _candidate_limit(top_k: int) -> int:
    return top_k * settings.retrieval_candidate_multiplier


async def retrieve_chunks(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    top_k: int,
    embedding_provider: EmbeddingProvider,
    scope: KnowledgeScope = KnowledgeScope.PRIVATE,
) -> list[RetrievedChunk]:
    started = time.perf_counter()
    query_embedding = await embedding_provider.embed_query(query)
    if len(query_embedding) != settings.embedding_dimension:
        raise ProviderError("Embedding provider returned an invalid vector shape")

    try:
        mode = parse_retrieval_mode(settings.retrieval_mode)
    except ValueError as exc:
        raise ProviderError(str(exc)) from exc

    if mode is RetrievalMode.VECTOR:
        chunks = await _retrieve_vector(db, space_id, user_id, query_embedding, top_k, scope)
    else:
        chunks = await _retrieve_hybrid(db, space_id, user_id, query_embedding, query, top_k, scope)

    log_event(
        logger,
        logging.DEBUG,
        "retrieval",
        mode=mode.value,
        scope=scope.value,
        top_k=top_k,
        candidates=len(chunks),
        question_length=len(query),
        duration_ms=monotonic_ms(started),
    )
    return chunks


async def _retrieve_vector(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int,
    scope: KnowledgeScope,
) -> list[RetrievedChunk]:
    if scope == KnowledgeScope.PRIVATE:
        return await _fetch_private_vector(db, space_id, user_id, query_embedding, top_k)
    if scope == KnowledgeScope.REFERENCE:
        return await _fetch_reference_vector(db, query_embedding, top_k)
    if scope == KnowledgeScope.COMBINED:
        private_candidates = await _fetch_private_vector(
            db, space_id, user_id, query_embedding, top_k
        )
        reference_candidates = await _fetch_reference_vector(db, query_embedding, top_k)
        return _merge_candidates(private_candidates, reference_candidates, top_k)
    raise ProviderError("Unsupported knowledge scope")


async def _retrieve_hybrid(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query_embedding: list[float],
    query: str,
    top_k: int,
    scope: KnowledgeScope,
) -> list[RetrievedChunk]:
    limit = _candidate_limit(top_k)
    lexical_weight = settings.retrieval_lexical_weight

    async def fused_private() -> list[RetrievedChunk]:
        return reciprocal_rank_fusion(
            [
                await _fetch_private_vector(db, space_id, user_id, query_embedding, limit),
                await _fetch_private_lexical(db, space_id, user_id, query_embedding, query, limit),
            ],
            k=settings.retrieval_rrf_k,
            weights=[1.0, lexical_weight],
        )

    async def fused_reference() -> list[RetrievedChunk]:
        return reciprocal_rank_fusion(
            [
                await _fetch_reference_vector(db, query_embedding, limit),
                await _fetch_reference_lexical(db, query_embedding, query, limit),
            ],
            k=settings.retrieval_rrf_k,
            weights=[1.0, lexical_weight],
        )

    if scope == KnowledgeScope.PRIVATE:
        candidates = await fused_private()
    elif scope == KnowledgeScope.REFERENCE:
        candidates = await fused_reference()
    elif scope == KnowledgeScope.COMBINED:
        # Fusion happens WITHIN each source kind; cross-kind ordering uses the
        # proven global cosine-score merge. Per-channel ranks from different
        # corpora are not directly comparable, and measuring equal-weight RRF
        # across kinds showed it displaces correct reference/private winners.
        candidates = _merge_candidates(await fused_private(), await fused_reference(), None)
    else:
        raise ProviderError("Unsupported knowledge scope")

    diversified = suppress_redundant_candidates(candidates)
    return diversified[:top_k]


def citation_from_chunk(chunk: RetrievedChunk) -> CitationResponse:
    return CitationResponse(
        source_id=chunk.source_id,
        source_kind=chunk.source_kind,
        document_id=uuid.UUID(chunk.document_id) if chunk.source_kind == "private" else None,
        reference_document_id=(
            uuid.UUID(chunk.document_id) if chunk.source_kind == "reference" else None
        ),
        document_name=chunk.document_name,
        page_number=chunk.page_number,
        chunk_id=uuid.UUID(chunk.chunk_id),
        excerpt=chunk.content,
        score=chunk.score,
    )


def _canonical_retrieved_source_id(
    source_id: str,
    by_source_id: dict[str, RetrievedChunk],
) -> str:
    """Resolve recoverable provider citation formatting without widening scope.

    Providers occasionally return the retrieved chunk UUID without the
    request-local ``private:``/``reference:`` namespace (or with the legacy
    ``chunk:`` prefix). Only a candidate that maps to an already retrieved
    chunk is accepted; unknown IDs remain unknown and are rejected below.
    """
    if source_id in by_source_id:
        return source_id
    raw_id = source_id.split(":", 1)[1] if ":" in source_id else source_id
    for prefix in ("private:", "reference:"):
        candidate = f"{prefix}{raw_id}"
        if candidate in by_source_id:
            return candidate
    return source_id


def _safe_answer_text(answer: str, source_ids: list[str]) -> str:
    """Remove only validated source IDs from prose without hiding bad citations."""
    identifiers: set[str] = set()
    for source_id in source_ids:
        raw_id = source_id.split(":", 1)[1] if ":" in source_id else source_id
        identifiers.update({raw_id, f"private:{raw_id}", f"reference:{raw_id}", f"chunk:{raw_id}"})

    display_answer = answer
    for identifier in sorted(identifiers, key=len, reverse=True):
        display_answer = display_answer.replace(identifier, "")
    display_answer = re.sub(r"\(\s*\)|\[\s*\]", "", display_answer)
    display_answer = re.sub(r"[ \t]+([,.;:!?])", r"\1", display_answer)
    display_answer = re.sub(r"[ \t]+", " ", display_answer).strip()
    if _INTERNAL_SOURCE_ID_PATTERN.search(display_answer):
        raise ProviderError("Answer provider returned internal citation identifiers")
    if not display_answer:
        raise ProviderError("Answer provider returned an empty display answer")
    return display_answer


async def search_space(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    top_k: int,
    embedding_provider: EmbeddingProvider,
) -> SearchResponse:
    chunks = await retrieve_chunks(db, space_id, user_id, query, top_k, embedding_provider)
    return SearchResponse(
        results=[citation_from_chunk(chunk) for chunk in chunks],
        embedding_model=embedding_provider.model_name,
    )


async def answer_question(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    top_k: int,
    embedding_provider: EmbeddingProvider,
    answer_provider: AnswerProvider,
    scope: KnowledgeScope = KnowledgeScope.PRIVATE,
) -> AnswerResponse:
    chunks = await retrieve_chunks(
        db, space_id, user_id, question, top_k, embedding_provider, scope
    )
    if not chunks:
        return AnswerResponse(
            answer="I could not find enough evidence in this knowledge space to answer that.",
            supported=False,
            citations=[],
            embedding_model=embedding_provider.model_name,
            answer_model=answer_provider.model_name,
        )

    generated = await answer_provider.answer(question, chunks)
    by_source_id = {chunk.source_id: chunk for chunk in chunks}
    unique_source_ids = list(
        dict.fromkeys(
            _canonical_retrieved_source_id(source_id, by_source_id)
            for source_id in generated.citation_source_ids
        )
    )
    if generated.supported and (
        not generated.answer.strip()
        or not unique_source_ids
        or any(source_id not in by_source_id for source_id in unique_source_ids)
    ):
        raise ProviderError("Answer provider returned unverifiable citations")
    if not generated.supported:
        return AnswerResponse(
            answer="I could not find enough evidence in this knowledge space to answer that.",
            supported=False,
            citations=[],
            embedding_model=embedding_provider.model_name,
            answer_model=answer_provider.model_name,
        )
    return AnswerResponse(
        answer=_safe_answer_text(generated.answer.strip(), unique_source_ids),
        supported=True,
        citations=[citation_from_chunk(by_source_id[source_id]) for source_id in unique_source_ids],
        embedding_model=embedding_provider.model_name,
        answer_model=answer_provider.model_name,
    )
