import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.errors import ProviderError
from app.domain.rag import (
    AnswerProvider,
    EmbeddingProvider,
    KnowledgeScope,
    RetrievedChunk,
    SourceKind,
)
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    KnowledgeSpace,
    ReferenceDocument,
    ReferenceDocumentChunk,
)
from app.schemas.document import AnswerResponse, CitationResponse, SearchResponse

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


async def _retrieve_private(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int,
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
        .limit(top_k)
    )
    return [
        RetrievedChunk(
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
        for chunk, document, score in result.all()
    ]


async def _retrieve_reference(
    db: AsyncSession,
    query_embedding: list[float],
    top_k: int,
) -> list[RetrievedChunk]:
    distance = ReferenceDocumentChunk.embedding.cosine_distance(query_embedding)
    result = await db.execute(
        select(ReferenceDocumentChunk, ReferenceDocument, (1 - distance).label("score"))
        .join(
            ReferenceDocument,
            ReferenceDocumentChunk.reference_document_id == ReferenceDocument.id,
        )
        .where(
            ReferenceDocument.status == "ready",
            distance <= 1 - settings.default_similarity_threshold,
        )
        .order_by(distance, ReferenceDocumentChunk.chunk_index)
        .limit(top_k)
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


def _merge_candidates(
    private_candidates: list[RetrievedChunk],
    reference_candidates: list[RetrievedChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    """Merge private + reference candidates, sort globally by score, apply global top_k.

    Tie-breaking is deterministic: score descending, then source kind, document id,
    page number, chunk index. No score boosts or reranking are applied.
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
    return combined[:top_k]


async def retrieve_chunks(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    top_k: int,
    embedding_provider: EmbeddingProvider,
    scope: KnowledgeScope = KnowledgeScope.PRIVATE,
) -> list[RetrievedChunk]:
    query_embedding = await embedding_provider.embed_query(query)
    if len(query_embedding) != settings.embedding_dimension:
        raise ProviderError("Embedding provider returned an invalid vector shape")

    if scope == KnowledgeScope.PRIVATE:
        return await _retrieve_private(db, space_id, user_id, query_embedding, top_k)
    if scope == KnowledgeScope.REFERENCE:
        return await _retrieve_reference(db, query_embedding, top_k)
    if scope == KnowledgeScope.COMBINED:
        private_candidates = await _retrieve_private(db, space_id, user_id, query_embedding, top_k)
        reference_candidates = await _retrieve_reference(db, query_embedding, top_k)
        return _merge_candidates(private_candidates, reference_candidates, top_k)
    raise ProviderError("Unsupported knowledge scope")


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
