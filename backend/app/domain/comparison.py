import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.domain.analysis import AnalysisSource


class ComparisonStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


MIN_COMPARISON_DOCUMENTS = 2
MAX_COMPARISON_DOCUMENTS = 4

MAX_COMPARISON_TITLE_LENGTH = 200
MAX_COMPARISON_SUMMARY_LENGTH = 2000
MAX_COMPARISON_LABEL_LENGTH = 200
MAX_COMPARISON_VALUE_LENGTH = 1000
MAX_COMPARISON_SYNTHESIS_LENGTH = 1000
MAX_COMPARISON_DESCRIPTION_LENGTH = 1000

MAX_COMPARISON_DIMENSIONS = 8
MAX_COMPARISON_KEY_DIFFERENCES = 6
MAX_COMPARISON_COMMONALITIES = 6

_DOCUMENT_REF_PREFIX = "document_"


def document_ref(position: int) -> str:
    """Request-local document label shown to the provider (``document_1``...)."""
    return f"{_DOCUMENT_REF_PREFIX}{position}"


def parse_document_ref(value: object) -> int | None:
    """Parse a provider-returned document ref back into a 1-based position.

    Returns ``None`` for anything that is not a well-formed ``document_<n>``
    reference; the server maps positions to real document IDs, so the provider
    can never address arbitrary database UUIDs.
    """
    if not isinstance(value, str):
        return None
    if not value.startswith(_DOCUMENT_REF_PREFIX):
        return None
    suffix = value[len(_DOCUMENT_REF_PREFIX) :]
    if not suffix.isdigit():
        return None
    position = int(suffix)
    return position if position >= 1 else None


@dataclass(frozen=True)
class ComparisonDocumentContext:
    """One selected document's full persisted content for the provider."""

    position: int
    document_id: uuid.UUID
    title: str
    sources: list[AnalysisSource]


@dataclass(frozen=True)
class DocumentComparisonContext:
    """Deterministic provider context: selected documents only, full chunks."""

    documents: list[ComparisonDocumentContext]
    focus: str | None

    def render(self) -> str:
        blocks: list[str] = []
        if self.focus:
            blocks.append(f"COMPARISON FOCUS {self.focus}")
        for document in self.documents:
            blocks.append(f"DOCUMENT {document_ref(document.position)}")
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
class ProviderComparisonFinding:
    """Untrusted per-document finding returned by a provider."""

    document_ref: str
    value: str | None
    not_identified: bool
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderComparisonDimension:
    """Untrusted comparison dimension returned by a provider."""

    label: str
    findings: list[ProviderComparisonFinding]
    synthesis: str | None
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderKeyDifference:
    """Untrusted key difference returned by a provider."""

    title: str
    description: str
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderCommonality:
    """Untrusted commonality returned by a provider."""

    title: str
    description: str
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderComparisonResult:
    """Untrusted structured result returned by a comparison provider."""

    title: str
    summary: str
    dimensions: list[ProviderComparisonDimension]
    key_differences: list[ProviderKeyDifference]
    commonalities: list[ProviderCommonality]


class DocumentComparisonProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def compare(
        self,
        context: DocumentComparisonContext,
    ) -> ProviderComparisonResult: ...


@dataclass(frozen=True)
class ComparisonCitation:
    """Trusted citation metadata entirely derived from stored chunks."""

    document_id: uuid.UUID
    chunk_id: str
    page_number: int
    excerpt: str


@dataclass(frozen=True)
class ValidatedComparisonFinding:
    """One server-validated finding for one selected document."""

    document_id: uuid.UUID
    value: str | None
    not_identified: bool
    sources: list[ComparisonCitation] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedComparisonDimension:
    """One server-validated comparison dimension."""

    label: str
    findings: list[ValidatedComparisonFinding]
    synthesis: str | None
    sources: list[ComparisonCitation] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedKeyDifference:
    """One server-validated key difference."""

    title: str
    description: str
    sources: list[ComparisonCitation] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedCommonality:
    """One server-validated commonality."""

    title: str
    description: str
    sources: list[ComparisonCitation] = field(default_factory=list)


@dataclass(frozen=True)
class ComparisonResult:
    """Trusted, server-validated structured comparison."""

    title: str
    summary: str
    dimensions: list[ValidatedComparisonDimension]
    key_differences: list[ValidatedKeyDifference]
    commonalities: list[ValidatedCommonality]
