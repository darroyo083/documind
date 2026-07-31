import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.errors import ProviderError
from app.domain.rag import AnswerProvider, EmbeddingProvider, RetrievedChunk
from app.infrastructure.models import Document, DocumentChunk, DocumentStatus, KnowledgeSpace
from app.schemas.document import AnswerResponse, CitationResponse, SearchResponse


def resolve_top_k(requested: int | None) -> int:
    top_k = requested or settings.default_top_k
    if top_k > settings.retrieval_max_top_k:
        raise ValueError(f"top_k must be no greater than {settings.retrieval_max_top_k}")
    return top_k


async def retrieve_chunks(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    top_k: int,
    embedding_provider: EmbeddingProvider,
) -> list[RetrievedChunk]:
    query_embedding = await embedding_provider.embed_query(query)
    if len(query_embedding) != settings.embedding_dimension:
        raise ProviderError("Embedding provider returned an invalid vector shape")

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
        .order_by(distance)
        .limit(top_k)
    )
    return [
        RetrievedChunk(
            source_id=f"chunk:{chunk.id}",
            document_id=str(document.id),
            document_name=document.original_filename,
            page_number=chunk.page_number,
            chunk_id=str(chunk.id),
            content=chunk.content,
            score=float(score),
        )
        for chunk, document, score in result.all()
    ]


def citation_from_chunk(chunk: RetrievedChunk) -> CitationResponse:
    return CitationResponse(
        source_id=chunk.source_id,
        document_id=uuid.UUID(chunk.document_id),
        document_name=chunk.document_name,
        page_number=chunk.page_number,
        chunk_id=uuid.UUID(chunk.chunk_id),
        excerpt=chunk.content,
        score=chunk.score,
    )


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
) -> AnswerResponse:
    chunks = await retrieve_chunks(db, space_id, user_id, question, top_k, embedding_provider)
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
    unique_source_ids = list(dict.fromkeys(generated.citation_source_ids))
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
        answer=generated.answer.strip(),
        supported=True,
        citations=[citation_from_chunk(by_source_id[source_id]) for source_id in unique_source_ids],
        embedding_model=embedding_provider.model_name,
        answer_model=answer_provider.model_name,
    )
