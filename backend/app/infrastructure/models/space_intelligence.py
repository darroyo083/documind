import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.intelligence import IntelligenceStatus
from app.infrastructure.database import Base

if TYPE_CHECKING:
    from app.infrastructure.models.knowledge_space import KnowledgeSpace


class SpaceIntelligenceStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SpaceIntelligence(Base):
    __tablename__ = "space_intelligence"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_space_intelligence_status_valid",
        ),
        CheckConstraint(
            "input_signature ~ '^[0-9a-f]{64}$'",
            name="ck_space_intelligence_signature_valid",
        ),
        UniqueConstraint(
            "knowledge_space_id",
            name="uq_space_intelligence_knowledge_space_id",
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
        String(20), nullable=False, default=IntelligenceStatus.PROCESSING.value
    )
    input_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_facts: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    contradictions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    dates: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    open_questions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
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

    space: Mapped["KnowledgeSpace"] = relationship(back_populates="intelligence")


# Re-export for API consumers that import the status enum.
Status = SpaceIntelligenceStatus
