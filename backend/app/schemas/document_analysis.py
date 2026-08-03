import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AnalysisCitationResponse(BaseModel):
    chunk_id: uuid.UUID
    page_number: int
    excerpt: str


class ImportantDateResponse(BaseModel):
    label: str
    value: str
    normalized_date: str | None
    sources: list[AnalysisCitationResponse]


class KeyFactResponse(BaseModel):
    label: str
    value: str
    sources: list[AnalysisCitationResponse]


class DocumentAnalysisResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    document_type: str
    normalized_title: str
    summary: str
    important_dates: list[ImportantDateResponse]
    key_facts: list[KeyFactResponse]
    provider: str
    model: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
