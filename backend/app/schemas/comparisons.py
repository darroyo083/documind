import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ComparisonCitationResponse(BaseModel):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    page_number: int
    excerpt: str


class ComparisonFindingResponse(BaseModel):
    document_id: uuid.UUID
    value: str | None
    not_identified: bool
    sources: list[ComparisonCitationResponse]


class ComparisonDimensionResponse(BaseModel):
    label: str
    findings: list[ComparisonFindingResponse]
    synthesis: str | None
    sources: list[ComparisonCitationResponse]


class ComparisonKeyDifferenceResponse(BaseModel):
    title: str
    description: str
    sources: list[ComparisonCitationResponse]


class ComparisonCommonalityResponse(BaseModel):
    title: str
    description: str
    sources: list[ComparisonCitationResponse]


class ComparisonMemberResponse(BaseModel):
    document_id: uuid.UUID
    original_filename: str
    position: int


class DocumentComparisonResponse(BaseModel):
    id: uuid.UUID
    status: str
    focus: str | None
    title: str
    summary: str
    documents: list[ComparisonMemberResponse]
    dimensions: list[ComparisonDimensionResponse]
    key_differences: list[ComparisonKeyDifferenceResponse]
    commonalities: list[ComparisonCommonalityResponse]
    provider: str
    model: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ComparisonSummaryResponse(BaseModel):
    id: uuid.UUID
    status: str
    focus: str | None
    title: str
    documents: list[ComparisonMemberResponse]
    created_at: datetime
    updated_at: datetime


class CreateComparisonRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=2, max_length=4)
    focus: str | None = None

    model_config = ConfigDict(extra="forbid")
