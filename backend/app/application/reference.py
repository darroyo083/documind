import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chunking import chunk_pages
from app.config import settings
from app.domain.errors import InvalidDocumentError, TextExtractionError
from app.domain.rag import EmbeddingProvider
from app.infrastructure.models import ReferenceDocument, ReferenceDocumentChunk
from app.infrastructure.pdf import PdfPageExtractor


async def find_by_sha256(db: AsyncSession, content_sha256: str) -> ReferenceDocument | None:
    result = await db.execute(
        select(ReferenceDocument).where(ReferenceDocument.content_sha256 == content_sha256)
    )
    return result.scalar_one_or_none()


async def import_reference_document(
    db: AsyncSession,
    path: Path,
    title: str,
    embedding_provider: EmbeddingProvider,
) -> tuple[ReferenceDocument, bool]:
    """Import a text-based PDF as an application-managed reference document.

    Returns ``(reference_document, created)``. ``created`` is False when the
    exact same source content (SHA-256) is already imported; no duplicate rows
    or chunks are created in that case.

    The import is atomic: the document and its chunks are committed in one
    transaction, so a failure leaves no partial reference rows.
    """
    normalized_title = (title or "").strip()
    if not normalized_title:
        raise ValueError("A reference document title is required")
    if len(normalized_title) > 500:
        raise ValueError("Reference document title is too long")

    if not path.is_file():
        raise InvalidDocumentError(f"Reference file not found: {path}")
    data = path.read_bytes()
    if not data:
        raise InvalidDocumentError("The reference file is empty")
    if not data.startswith(b"%PDF-"):
        raise InvalidDocumentError("Reference documents must be PDF files")

    content_sha256 = hashlib.sha256(data).hexdigest()
    existing = await find_by_sha256(db, content_sha256)
    if existing is not None:
        return existing, False

    pages = await PdfPageExtractor().extract(path)
    chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise TextExtractionError("No meaningful text could be extracted from the PDF")
    embeddings = await embedding_provider.embed_texts([chunk.content for chunk in chunks])
    if len(embeddings) != len(chunks) or any(
        len(embedding) != settings.embedding_dimension for embedding in embeddings
    ):
        raise TextExtractionError("Embedding provider returned an invalid vector shape")

    try:
        reference_document = ReferenceDocument(
            title=normalized_title,
            original_filename=path.name,
            status="ready",
            content_sha256=content_sha256,
            page_count=len(pages),
        )
        db.add(reference_document)
        await db.flush()
        db.add_all(
            [
                ReferenceDocumentChunk(
                    reference_document_id=reference_document.id,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ]
        )
        await db.commit()
        await db.refresh(reference_document)
        return reference_document, True
    except Exception:
        await db.rollback()
        raise


async def list_reference_documents(
    db: AsyncSession,
) -> list[ReferenceDocument]:
    result = await db.execute(select(ReferenceDocument).order_by(ReferenceDocument.title))
    return list(result.scalars().all())
