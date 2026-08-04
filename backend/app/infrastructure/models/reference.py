import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.infrastructure.database import Base


class ReferenceDocument(Base):
    __tablename__ = "reference_documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'failed')",
            name="ck_reference_documents_status_valid",
        ),
        CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name="ck_reference_documents_page_count_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["ReferenceDocumentChunk"]] = relationship(
        back_populates="reference_document",
        cascade="all, delete-orphan",
        order_by="ReferenceDocumentChunk.chunk_index",
    )


class ReferenceDocumentChunk(Base):
    __tablename__ = "reference_document_chunks"
    __table_args__ = (
        CheckConstraint(
            "page_number > 0", name="ck_reference_document_chunks_page_number_positive"
        ),
        CheckConstraint("chunk_index >= 0", name="ck_reference_document_chunks_index_nonnegative"),
        CheckConstraint(
            "length(content) > 0", name="ck_reference_document_chunks_content_nonempty"
        ),
        UniqueConstraint(
            "reference_document_id",
            "chunk_index",
            name="uq_reference_document_chunks_position",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reference_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dimension), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reference_document: Mapped[ReferenceDocument] = relationship(back_populates="chunks")
