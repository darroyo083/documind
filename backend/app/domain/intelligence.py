"""Domain contract for Space Intelligence (PoC 4C).

Space Intelligence synthesizes cross-document insights (summary, key facts,
contradictions, dates/deadlines, open questions) for a knowledge space. It
mirrors the comparison/analysis contract style: untrusted ``Provider*``
dataclasses for the model output, trusted ``Validated*`` dataclasses for
server-validated results, and a ``SpaceIntelligenceProvider`` Protocol.

Every factual item must cite valid source IDs; the server maps source IDs back
to real chunks and derives citation metadata. The provider never sees real
database UUIDs (sources are rendered as ``chunk:<id>`` labels).
"""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.domain.analysis import AnalysisSource


class IntelligenceStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


MIN_INTELLIGENCE_DOCUMENTS = 1
MAX_INTELLIGENCE_DOCUMENTS = 20

MAX_INTELLIGENCE_SUMMARY_LENGTH = 2000
MAX_INTELLIGENCE_LABEL_LENGTH = 200
MAX_INTELLIGENCE_VALUE_LENGTH = 1000

MAX_INTELLIGENCE_KEY_FACTS = 8
MAX_INTELLIGENCE_CONTRADICTIONS = 5
MAX_INTELLIGENCE_DATES = 8
MAX_INTELLIGENCE_OPEN_QUESTIONS = 5


@dataclass(frozen=True)
class SpaceIntelligenceContext:
    """Deterministic provider context: every READY document's full chunks."""

    documents: list["IntelligenceDocumentContext"]

    def render(self) -> str:
        blocks: list[str] = []
        for document in self.documents:
            blocks.append(f"DOCUMENT {document.document_id}")
            blocks.append(f"TITLE {document.title}")
            for source in document.sources:
                blocks.extend(
                    [
                        f"SOURCE {source.source_id}",
                        f"PAGE {source.page_number}",
                        source.content,
                    ]
                )
        return "\n".join(blocks)

    def total_chars(self) -> int:
        return len(self.render())


@dataclass(frozen=True)
class IntelligenceDocumentContext:
    """One eligible document's full persisted content for the provider."""

    document_id: uuid.UUID
    title: str
    sources: list[AnalysisSource]


@dataclass(frozen=True)
class ProviderKeyFact:
    title: str
    detail: str
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderContradiction:
    topic: str
    first_claim: str
    first_source_ids: list[str]
    second_claim: str
    second_source_ids: list[str]


@dataclass(frozen=True)
class ProviderDate:
    label: str
    date_text: str
    context: str
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderOpenQuestion:
    question: str
    explanation: str
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderSpaceIntelligence:
    """Untrusted structured result returned by an intelligence provider."""

    summary: str
    key_facts: list[ProviderKeyFact]
    contradictions: list[ProviderContradiction]
    dates: list[ProviderDate]
    open_questions: list[ProviderOpenQuestion]


class SpaceIntelligenceProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def analyze(
        self,
        context: SpaceIntelligenceContext,
    ) -> ProviderSpaceIntelligence: ...


@dataclass(frozen=True)
class IntelligenceCitation:
    """Trusted citation metadata entirely derived from stored chunks."""

    document_id: uuid.UUID
    document_name: str
    chunk_id: str
    page_number: int
    excerpt: str


@dataclass(frozen=True)
class ValidatedKeyFact:
    title: str
    detail: str
    sources: list[IntelligenceCitation] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedContradiction:
    topic: str
    first_claim: str
    second_claim: str
    first_sources: list[IntelligenceCitation] = field(default_factory=list)
    second_sources: list[IntelligenceCitation] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedDate:
    label: str
    date_text: str
    context: str
    sources: list[IntelligenceCitation] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedOpenQuestion:
    question: str
    explanation: str
    sources: list[IntelligenceCitation] = field(default_factory=list)


@dataclass(frozen=True)
class SpaceIntelligenceResult:
    """Trusted, server-validated structured intelligence."""

    summary: str
    key_facts: list[ValidatedKeyFact]
    contradictions: list[ValidatedContradiction]
    dates: list[ValidatedDate]
    open_questions: list[ValidatedOpenQuestion]
