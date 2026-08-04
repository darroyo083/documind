from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class KnowledgeScope(StrEnum):
    PRIVATE = "private"
    REFERENCE = "reference"
    COMBINED = "combined"


def parse_knowledge_scope(value: object) -> KnowledgeScope:
    """Parse an untrusted scope value; omitted/None means private (backward compatible)."""
    if value is None:
        return KnowledgeScope.PRIVATE
    if not isinstance(value, str):
        raise ValueError("knowledge_scope must be one of: private, reference, combined")
    try:
        return KnowledgeScope(value)
    except ValueError:
        raise ValueError("knowledge_scope must be one of: private, reference, combined") from None


class SourceKind(StrEnum):
    PRIVATE = "private"
    REFERENCE = "reference"


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
    text: str


@dataclass(frozen=True)
class TextChunk:
    page_number: int
    chunk_index: int
    content: str


@dataclass(frozen=True)
class RetrievedChunk:
    source_id: str
    source_kind: str
    document_id: str
    document_name: str
    page_number: int
    chunk_id: str
    content: str
    score: float
    chunk_index: int = 0


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    supported: bool
    citation_source_ids: list[str]


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class AnswerProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def answer(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer: ...


class DocumentStorage(Protocol):
    async def save(self, data: bytes) -> str: ...

    async def delete(self, storage_key: str) -> None: ...

    def path_for(self, storage_key: str): ...
