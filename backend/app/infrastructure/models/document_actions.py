import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
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

from app.domain.actions import ActionSetStatus, ActionStatus, ActionType
from app.infrastructure.database import Base

if TYPE_CHECKING:
    from app.infrastructure.models.document import Document

_ACTION_TYPES = ", ".join(f"'{item.value}'" for item in ActionType)


class DocumentActionSet(Base):
    __tablename__ = "document_action_sets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_document_action_sets_status_valid",
        ),
        UniqueConstraint("document_id", name="uq_document_action_sets_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ActionSetStatus.PROCESSING.value
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    actions: Mapped[list["DocumentAction"]] = relationship(
        back_populates="action_set",
        cascade="all, delete-orphan",
        order_by="DocumentAction.position",
    )

    document: Mapped["Document"] = relationship(back_populates="action_set")


class DocumentAction(Base):
    __tablename__ = "document_actions"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_document_actions_position_nonnegative"),
        CheckConstraint(
            f"action_type IN ({_ACTION_TYPES})",
            name="ck_document_actions_action_type_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed')",
            name="ck_document_actions_status_valid",
        ),
        UniqueConstraint("action_set_id", "position", name="uq_document_actions_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_action_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    timing_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ActionStatus.PENDING.value
    )
    sources: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    action_set: Mapped[DocumentActionSet] = relationship(back_populates="actions")
