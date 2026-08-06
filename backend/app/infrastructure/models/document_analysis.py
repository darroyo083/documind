import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.analysis import DocumentType
from app.infrastructure.database import Base

if TYPE_CHECKING:
    from app.infrastructure.models.document import Document


class DocumentAnalysisStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


_SUPPORTED_TYPES = ", ".join(f"'{item.value}'" for item in DocumentType)


class DocumentAnalysis(Base):
    __tablename__ = "document_analyses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_document_analyses_status_valid",
        ),
        CheckConstraint(
            f"document_type IN ({_SUPPORTED_TYPES})",
            name="ck_document_analyses_document_type_valid",
        ),
        UniqueConstraint("document_id", name="uq_document_analyses_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DocumentAnalysisStatus.PROCESSING.value
    )
    document_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default=DocumentType.UNKNOWN.value
    )
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    important_dates: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    key_facts: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="analysis")  # noqa: F821


# Re-export for API consumers that import the status enum.
Status = DocumentAnalysisStatus
