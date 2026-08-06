import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.comparison import ComparisonStatus
from app.infrastructure.database import Base

if TYPE_CHECKING:
    from app.infrastructure.models.document import Document
    from app.infrastructure.models.knowledge_space import KnowledgeSpace


class DocumentComparisonStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DocumentComparison(Base):
    __tablename__ = "document_comparisons"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_document_comparisons_status_valid",
        ),
        CheckConstraint(
            "comparison_signature ~ '^[0-9a-f]{64}$'",
            name="ck_document_comparisons_signature_valid",
        ),
        UniqueConstraint(
            "knowledge_space_id",
            "comparison_signature",
            name="uq_document_comparisons_signature",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ComparisonStatus.PROCESSING.value
    )
    comparison_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    focus: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    comparison_dimensions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    key_differences: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    commonalities: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
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

    members: Mapped[list["DocumentComparisonDocument"]] = relationship(
        back_populates="comparison",
        cascade="all, delete-orphan",
        order_by="DocumentComparisonDocument.position",
    )

    space: Mapped["KnowledgeSpace"] = relationship(back_populates="comparisons")  # noqa: F821


class DocumentComparisonDocument(Base):
    __tablename__ = "document_comparison_documents"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_document_comparison_documents_position"),
        UniqueConstraint(
            "comparison_id",
            "document_id",
            name="uq_document_comparison_documents_member",
        ),
        UniqueConstraint(
            "comparison_id",
            "position",
            name="uq_document_comparison_documents_position",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_comparisons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    comparison: Mapped[DocumentComparison] = relationship(back_populates="members")
    document: Mapped["Document"] = relationship(back_populates="comparison_members")  # noqa: F821


# Re-export for API consumers that import the status enum.
Status = DocumentComparisonStatus
