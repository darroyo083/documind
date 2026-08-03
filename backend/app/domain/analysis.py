import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class DocumentType(StrEnum):
    CONTRACT = "contract"
    INVOICE = "invoice"
    INSURANCE_POLICY = "insurance_policy"
    BANK_STATEMENT = "bank_statement"
    TAX_DOCUMENT = "tax_document"
    EMPLOYMENT_DOCUMENT = "employment_document"
    HOUSING_DOCUMENT = "housing_document"
    PENSION_DOCUMENT = "pension_document"
    OFFICIAL_LETTER = "official_letter"
    RECEIPT = "receipt"
    REPORT = "report"
    OTHER = "other"
    UNKNOWN = "unknown"


def parse_document_type(value: object) -> DocumentType:
    """Map an untrusted provider type to the controlled taxonomy.

    The provider must never be able to invent arbitrary type values. Values that
    fall outside the controlled taxonomy are deliberately mapped to ``other``;
    missing values map to ``unknown``.
    """
    if value is None:
        return DocumentType.UNKNOWN
    if not isinstance(value, str):
        return DocumentType.OTHER
    try:
        return DocumentType(value)
    except ValueError:
        return DocumentType.OTHER


class AnalysisStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class AnalysisSource:
    """One trusted source of document content available to the provider."""

    source_id: str
    page_number: int
    content: str


@dataclass(frozen=True)
class DocumentAnalysisContext:
    """Deterministic provider context built from persisted chunks."""

    document_id: uuid.UUID
    sources: list[AnalysisSource]

    def render(self) -> str:
        blocks: list[str] = []
        for source in self.sources:
            blocks.extend(
                [
                    f"SOURCE {source.source_id}",
                    f"PAGE {source.page_number}",
                    source.content,
                ]
            )
        return "\n".join(blocks)


@dataclass(frozen=True)
class ProviderImportantDate:
    """Untrusted date extracted by the provider."""

    label: str
    value: str
    normalized_date: str | None
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderKeyFact:
    """Untrusted fact extracted by the provider."""

    label: str
    value: str
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderDocumentAnalysis:
    """Untrusted structured result returned by a provider."""

    document_type: str
    normalized_title: str
    summary: str
    important_dates: list[ProviderImportantDate]
    key_facts: list[ProviderKeyFact]


class DocumentAnalysisProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def analyze(
        self,
        context: DocumentAnalysisContext,
    ) -> ProviderDocumentAnalysis: ...


@dataclass(frozen=True)
class AnalysisCitation:
    """Trusted citation metadata entirely derived from stored chunks."""

    chunk_id: str
    page_number: int
    excerpt: str


@dataclass(frozen=True)
class ValidatedImportantDate:
    label: str
    value: str
    normalized_date: str | None
    sources: list[AnalysisCitation] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedKeyFact:
    label: str
    value: str
    sources: list[AnalysisCitation] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentAnalysisResult:
    """Trusted, server-validated structured analysis."""

    document_type: DocumentType
    normalized_title: str
    summary: str
    important_dates: list[ValidatedImportantDate]
    key_facts: list[ValidatedKeyFact]
