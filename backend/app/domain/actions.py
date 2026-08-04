from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from app.domain.analysis import AnalysisCitation, AnalysisSource


class ActionType(StrEnum):
    REQUIRED_ACTION = "required_action"
    DEADLINE = "deadline"
    REMINDER = "reminder"
    RECOMMENDED_ACTION = "recommended_action"


class ActionSetStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ActionStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


@dataclass(frozen=True)
class DocumentActionContext:
    """Deterministic provider context built from persisted chunks."""

    document_id: str
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
class ProviderAction:
    """Untrusted action returned by a provider."""

    action_type: str
    title: str
    description: str | None
    timing_text: str | None
    due_date: str | None
    source_ids: list[str]


@dataclass(frozen=True)
class ProviderDocumentActions:
    """Untrusted structured result returned by an action provider."""

    actions: list[ProviderAction]


class DocumentActionProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate_actions(
        self,
        context: DocumentActionContext,
    ) -> ProviderDocumentActions: ...


@dataclass(frozen=True)
class ValidatedAction:
    """Trusted, server-validated action."""

    action_type: ActionType
    title: str
    description: str | None
    timing_text: str | None
    due_date: date | None
    citations: list[AnalysisCitation]
