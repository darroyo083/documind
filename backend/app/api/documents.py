import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.comparisons import delete_comparisons_for_document
from app.application.dependencies import (
    get_answer_provider,
    get_document_storage,
    get_embedding_provider,
)
from app.application.documents import (
    get_owned_document,
    get_owned_space,
    ingest_document,
)
from app.application.retrieval import answer_question, resolve_top_k, search_space
from app.auth import get_current_user
from app.domain.errors import InvalidDocumentError, ProviderError, TextExtractionError
from app.domain.rag import AnswerProvider, DocumentStorage, EmbeddingProvider, parse_knowledge_scope
from app.infrastructure.database import get_db
from app.infrastructure.models import Document, User
from app.schemas.document import (
    AnswerResponse,
    AskRequest,
    DocumentResponse,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/knowledge-spaces/{space_id}", tags=["documents"])


async def require_owned_space(db: AsyncSession, space_id: uuid.UUID, user_id: uuid.UUID) -> None:
    if await get_owned_space(db, space_id, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    space_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
):
    await require_owned_space(db, space_id, current_user.id)
    try:
        return await ingest_document(db, space_id, file, storage, embedding_provider)
    except (InvalidDocumentError, TextExtractionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await file.close()


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_space(db, space_id, current_user.id)
    result = await db.execute(
        select(Document)
        .where(Document.knowledge_space_id == space_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await get_owned_document(db, space_id, document_id, current_user.id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return document


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: DocumentStorage = Depends(get_document_storage),
):
    document = await get_owned_document(db, space_id, document_id, current_user.id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await delete_comparisons_for_document(db, document.id)
    await storage.delete(document.storage_key)
    await db.delete(document)
    await db.commit()


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    space_id: uuid.UUID,
    body: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
):
    await require_owned_space(db, space_id, current_user.id)
    try:
        return await search_space(
            db,
            space_id,
            current_user.id,
            body.query,
            resolve_top_k(body.top_k),
            embedding_provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/ask", response_model=AnswerResponse)
async def ask_documents(
    space_id: uuid.UUID,
    body: AskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    answer_provider: AnswerProvider = Depends(get_answer_provider),
):
    await require_owned_space(db, space_id, current_user.id)
    try:
        scope = parse_knowledge_scope(body.knowledge_scope)
        return await answer_question(
            db,
            space_id,
            current_user.id,
            body.question,
            resolve_top_k(body.top_k),
            embedding_provider,
            answer_provider,
            scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
