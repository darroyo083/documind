import uuid

from pydantic import BaseModel


class GlobalSearchHitResponse(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    space_id: uuid.UUID
    space_name: str
    page_number: int
    excerpt: str
    score: float
