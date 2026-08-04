import uuid
from datetime import datetime

from pydantic import BaseModel


class ReferenceDocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    original_filename: str
    page_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
