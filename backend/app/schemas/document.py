import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import settings


class DocumentResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    media_type: str
    file_size: int
    page_count: int | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SearchRequest(BaseModel):
    query: str = Field(max_length=settings.max_question_length)
    top_k: int | None = Field(default=None, ge=1)

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Query must not be empty")
        return stripped


class AskRequest(BaseModel):
    question: str = Field(max_length=settings.max_question_length)
    top_k: int | None = Field(default=None, ge=1)
    knowledge_scope: Literal["private", "reference", "combined"] | None = None

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question must not be empty")
        return stripped


class CitationResponse(BaseModel):
    source_id: str
    source_kind: str
    document_id: uuid.UUID | None
    reference_document_id: uuid.UUID | None
    document_name: str
    page_number: int
    chunk_id: uuid.UUID
    excerpt: str
    score: float


class SearchResponse(BaseModel):
    results: list[CitationResponse]
    embedding_model: str


class AnswerResponse(BaseModel):
    answer: str
    supported: bool
    citations: list[CitationResponse]
    embedding_model: str
    answer_model: str
