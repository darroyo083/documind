import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ActionCitationResponse(BaseModel):
    chunk_id: uuid.UUID
    page_number: int
    excerpt: str


class ActionItemResponse(BaseModel):
    id: uuid.UUID
    action_type: str
    title: str
    description: str | None
    timing_text: str | None
    due_date: date | None
    status: str
    completed_at: datetime | None
    sources: list[ActionCitationResponse]

    model_config = ConfigDict(from_attributes=True)


class DocumentActionsResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    provider: str
    model: str
    actions: list[ActionItemResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActionStatusUpdate(BaseModel):
    status: Literal["pending", "completed"]

    model_config = ConfigDict(extra="forbid")
