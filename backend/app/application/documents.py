import hashlib
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePath

from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chunking import chunk_pages
from app.config import settings
from app.domain.errors import (
    DocumentStateError,
    DuplicateDocumentError,
    InvalidDocumentError,
    ProviderError,
    TextExtractionError,
)
from app.domain.rag import DocumentStorage, EmbeddingProvider
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    KnowledgeSpace,
)
from app.infrastructure.pdf import PdfPageExtractor
from app.observability import log_event, monotonic_ms

logger = logging.getLogger("documind.ingestion")


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


async def find_duplicate(
    db: AsyncSession,
    space_id: uuid.UUID,
    content_sha256: str,
) -> Document | None:
    result = await db.execute(
        select(Document).where(
            Document.knowledge_space_id == space_id,
            Document.content_sha256 == content_sha256,
        )
    )
    return result.scalar_one_or_none()


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
        content_sha256=hashlib.sha256(data).hexdigest(),
        status=DocumentStatus.PROCESSING.value,
        processing_started_at=func.now(),
    )

    duplicate = await find_duplicate(db, space_id, document.content_sha256 or "")
    if duplicate is not None:
        await storage.delete(storage_key)
        raise DuplicateDocumentError(str(duplicate.id))

    db.add(document)
    try:
        await db.commit()
    except IntegrityError as exc:
        # Two concurrent uploads of identical content both pass the SELECT
        # above; the partial unique index decides the winner and the loser is
        # translated into the same structured 409 instead of a 500.
        await db.rollback()
        await storage.delete(storage_key)
        winner = await find_duplicate(db, space_id, document.content_sha256 or "")
        if winner is None:
            raise
        raise DuplicateDocumentError(str(winner.id)) from exc
    await db.refresh(document)

    await _process_document(db, document, storage, embedding_provider)
    await db.refresh(document)
    return document


FAILURE_CODE_NO_EXTRACTABLE_TEXT = "no_extractable_text"
FAILURE_CODE_EXTRACTION_FAILED = "extraction_failed"
FAILURE_CODE_PROCESSING_FAILED = "processing_failed"


def failure_code_for(error: Exception) -> str:
    if isinstance(error, TextExtractionError):
        return FAILURE_CODE_NO_EXTRACTABLE_TEXT
    if isinstance(error, InvalidDocumentError):
        return FAILURE_CODE_EXTRACTION_FAILED
    return FAILURE_CODE_PROCESSING_FAILED


def _mark_failed(document: Document, exc: Exception) -> None:
    document.status = DocumentStatus.FAILED.value
    document.error_message = str(exc)
    document.failure_code = failure_code_for(exc)


async def _process_document(
    db: AsyncSession,
    document: Document,
    storage: DocumentStorage,
    embedding_provider: EmbeddingProvider,
) -> None:
    """Extract, chunk, embed, and finalize one document (READY or FAILED).

    On failure the document is marked FAILED with a safe ``failure_code`` and the
    storage file is KEPT so the document can be retried without re-uploading.
    """
    started = time.perf_counter()
    try:
        extraction_started = time.perf_counter()
        pages = await PdfPageExtractor().extract(storage.path_for(document.storage_key))
        chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            raise TextExtractionError("No meaningful text could be extracted from the PDF")
        extraction_ms = monotonic_ms(extraction_started)

        embedding_started = time.perf_counter()
        embeddings = await embedding_provider.embed_texts([chunk.content for chunk in chunks])
        if len(embeddings) != len(chunks) or any(
            len(embedding) != settings.embedding_dimension for embedding in embeddings
        ):
            raise ProviderError("Embedding provider returned an invalid vector shape")
        embedding_ms = monotonic_ms(embedding_started)

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
        document.failure_code = None
        await db.commit()
        log_event(
            logger,
            logging.INFO,
            "ingestion_ready",
            document_id=str(document.id),
            page_count=len(pages),
            chunk_count=len(chunks),
            extraction_ms=extraction_ms,
            embedding_ms=embedding_ms,
            duration_ms=monotonic_ms(started),
        )
    except (InvalidDocumentError, TextExtractionError, ProviderError) as exc:
        await db.rollback()
        _mark_failed(document, exc)
        await db.commit()
        log_event(
            logger,
            logging.WARNING,
            "ingestion_failed",
            document_id=str(document.id),
            failure_code=document.failure_code,
            duration_ms=monotonic_ms(started),
        )
    except Exception as exc:
        # Unexpected failures must still reach a terminal state instead of
        # leaving the document stuck in PROCESSING forever. The storage file is
        # kept so the document can be retried. The client-facing message stays
        # curated: str(exc) may contain driver, SQL, or filesystem internals.
        await db.rollback()
        _mark_failed(document, exc)
        document.error_message = "The document could not be processed. You can retry it."
        await db.commit()
        log_event(
            logger,
            logging.ERROR,
            "ingestion_unexpected_failure",
            document_id=str(document.id),
            error_type=type(exc).__name__,
            detail=str(exc),
            duration_ms=monotonic_ms(started),
            exc_info=True,
        )


async def retry_document(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    storage: DocumentStorage,
    embedding_provider: EmbeddingProvider,
) -> Document | None:
    """Reprocess a FAILED (or stale-PROCESSING) document's existing file in place.

    Returns ``None`` when the document is not the user's (reported as 404).
    Raises :class:`DocumentStateError` when the document cannot be retried. The
    transition into PROCESSING is a compare-and-set UPDATE so concurrent
    retries never launch duplicate processing, and a PROCESSING claim older
    than ``DOCUMENT_STALE_AFTER_SECONDS`` is reclaimed atomically - a crash can
    no longer strand a document in an unrecoverable state.
    """
    document = await get_owned_document(db, space_id, document_id, user_id)
    if document is None:
        return None

    cutoff = datetime.now(UTC) - timedelta(seconds=settings.document_stale_after_seconds)
    result = await db.execute(
        update(Document)
        .where(
            Document.id == document.id,
            (Document.status == DocumentStatus.FAILED.value)
            | (
                (Document.status == DocumentStatus.PROCESSING.value)
                & Document.processing_started_at.is_not(None)
                & (Document.processing_started_at < cutoff)
            ),
        )
        .values(
            status=DocumentStatus.PROCESSING.value,
            error_message=None,
            failure_code=None,
            processing_started_at=func.now(),
        )
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise DocumentStateError("Only failed documents can be retried")
    await db.commit()
    await db.refresh(document)

    await _process_document(db, document, storage, embedding_provider)
    await db.refresh(document)
    return document
