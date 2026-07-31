from dataclasses import dataclass
from typing import Protocol


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
    document_id: str
    document_name: str
    page_number: int
    chunk_id: str
    content: str
    score: float


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
