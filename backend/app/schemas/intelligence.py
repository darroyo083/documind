import uuid
from datetime import datetime

from pydantic import BaseModel


class IntelligenceCitationResponse(BaseModel):
    document_id: uuid.UUID
    document_name: str
    chunk_id: uuid.UUID
    page_number: int
    excerpt: str


class IntelligenceKeyFactResponse(BaseModel):
    title: str
    detail: str
    sources: list[IntelligenceCitationResponse]


class IntelligenceContradictionResponse(BaseModel):
    topic: str
    first_claim: str
    first_sources: list[IntelligenceCitationResponse]
    second_claim: str
    second_sources: list[IntelligenceCitationResponse]


class IntelligenceDateResponse(BaseModel):
    label: str
    date_text: str
    context: str
    sources: list[IntelligenceCitationResponse]


class IntelligenceOpenQuestionResponse(BaseModel):
    question: str
    explanation: str
    sources: list[IntelligenceCitationResponse]


class SpaceIntelligenceResponse(BaseModel):
    status: str
    is_stale: bool
    ready_document_count: int
    summary: str
    key_facts: list[IntelligenceKeyFactResponse]
    contradictions: list[IntelligenceContradictionResponse]
    dates: list[IntelligenceDateResponse]
    open_questions: list[IntelligenceOpenQuestionResponse]
    provider: str | None
    model: str | None
    error_message: str | None
    created_at: datetime | None
    updated_at: datetime | None
