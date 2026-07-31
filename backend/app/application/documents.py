import uuid
from pathlib import PurePath

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chunking import chunk_pages
from app.config import settings
from app.domain.errors import InvalidDocumentError, ProviderError, TextExtractionError
from app.domain.rag import DocumentStorage, EmbeddingProvider
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    KnowledgeSpace,
)
from app.infrastructure.pdf import PdfPageExtractor


async def get_owned_space(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
) -> KnowledgeSpace | None:
    result = await db.execute(
        select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_owned_document(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Document | None:
    result = await db.execute(
        select(Document)
        .join(KnowledgeSpace, Document.knowledge_space_id == KnowledgeSpace.id)
        .where(
            Document.id == document_id,
            Document.knowledge_space_id == space_id,
            KnowledgeSpace.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def safe_filename(filename: str | None) -> str:
    normalized = (filename or "document.pdf").replace("\\", "/")
    basename = PurePath(normalized).name.strip()
    if not basename or len(basename) > 255:
        raise InvalidDocumentError("The PDF filename is invalid")
    return basename


async def read_pdf_upload(upload: UploadFile) -> bytes:
    if upload.content_type != "application/pdf":
        raise InvalidDocumentError("Only PDF files are supported")

    limit = settings.max_upload_size_mb * 1024 * 1024
    parts: list[bytes] = []
    size = 0
    while chunk := await upload.read(min(1024 * 1024, limit + 1 - size)):
        size += len(chunk)
        if size > limit:
            raise InvalidDocumentError(
                f"PDF must be no larger than {settings.max_upload_size_mb} MB"
            )
        parts.append(chunk)
    data = b"".join(parts)
    if not data:
        raise InvalidDocumentError("The PDF is empty")
    if not data.startswith(b"%PDF-"):
        raise InvalidDocumentError("The uploaded file is not a PDF")
    return data


async def ingest_document(
    db: AsyncSession,
    space_id: uuid.UUID,
    upload: UploadFile,
    storage: DocumentStorage,
    embedding_provider: EmbeddingProvider,
) -> Document:
    filename = safe_filename(upload.filename)
    data = await read_pdf_upload(upload)
    storage_key = await storage.save(data)
    document = Document(
        knowledge_space_id=space_id,
        original_filename=filename,
        storage_key=storage_key,
        media_type="application/pdf",
        file_size=len(data),
        status=DocumentStatus.PROCESSING.value,
    )
    db.add(document)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await storage.delete(storage_key)
        raise
    await db.refresh(document)

    try:
        pages = await PdfPageExtractor().extract(storage.path_for(storage_key))
        chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            raise TextExtractionError("No meaningful text could be extracted from the PDF")
        embeddings = await embedding_provider.embed_texts([chunk.content for chunk in chunks])
        if len(embeddings) != len(chunks) or any(
            len(embedding) != settings.embedding_dimension for embedding in embeddings
        ):
            raise ProviderError("Embedding provider returned an invalid vector shape")

        db.add_all(
            [
                DocumentChunk(
                    document_id=document.id,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    character_count=len(chunk.content),
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ]
        )
        document.page_count = len(pages)
        document.status = DocumentStatus.READY.value
        document.error_message = None
        await db.commit()
        await db.refresh(document)
        return document
    except (InvalidDocumentError, TextExtractionError, ProviderError) as exc:
        await db.rollback()
        document.status = DocumentStatus.FAILED.value
        document.error_message = str(exc)
        await db.commit()
        await storage.delete(storage_key)
        raise
