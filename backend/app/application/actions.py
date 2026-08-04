import uuid
from datetime import UTC, date, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.analysis import load_ordered_chunks
from app.application.documents import get_owned_document
from app.config import settings
from app.domain.actions import (
    ActionSetStatus,
    ActionStatus,
    ActionType,
    DocumentActionContext,
    DocumentActionProvider,
    ProviderDocumentActions,
    ValidatedAction,
)
from app.domain.analysis import AnalysisCitation, AnalysisSource
from app.domain.errors import (
    ActionConflictError,
    ActionContextTooLargeError,
    ActionNotFoundError,
    ActionStateError,
    ActionValidationError,
)
from app.infrastructure.analysis_providers import important_date_normalized
from app.infrastructure.models import (
    Document,
    DocumentAction,
    DocumentActionSet,
    DocumentChunk,
    DocumentStatus,
    KnowledgeSpace,
)


def chunk_source_id(chunk: DocumentChunk) -> str:
    return f"chunk:{chunk.id}"


def build_action_context(
    document: Document,
    chunks: list[DocumentChunk],
    max_context_chars: int,
) -> DocumentActionContext:
    sources = [
        AnalysisSource(
            source_id=chunk_source_id(chunk),
            page_number=chunk.page_number,
            content=chunk.content,
        )
        for chunk in chunks
    ]
    context = DocumentActionContext(document_id=str(document.id), sources=sources)
    if len(context.render()) > max_context_chars:
        raise ActionContextTooLargeError(
            "Document exceeds the supported action context size; "
            f"the limit is {max_context_chars} characters"
        )
    return context


def _validate_sources(
    source_ids: list[str],
    chunks_by_source_id: dict[str, DocumentChunk],
) -> list[AnalysisCitation]:
    unique_ids = list(dict.fromkeys(source_ids))
    if len(unique_ids) > settings.action_max_sources_per_item:
        raise ActionValidationError("An action references more sources than the configured maximum")
    citations: list[AnalysisCitation] = []
    for source_id in unique_ids:
        chunk = chunks_by_source_id.get(source_id)
        if chunk is None:
            raise ActionValidationError(
                f"Provider referenced an unknown or unauthorized source: {source_id}"
            )
        citations.append(
            AnalysisCitation(
                chunk_id=str(chunk.id),
                page_number=chunk.page_number,
                excerpt=chunk.content[: settings.action_excerpt_chars],
            )
        )
    if not citations:
        raise ActionValidationError("An action has no supporting evidence")
    return citations


def _dedupe_actions(
    actions: list[ValidatedAction],
) -> list[ValidatedAction]:
    """Remove exact duplicates after normalization, merging valid source IDs.

    Exact duplicate = same action_type, title, timing_text, due_date.
    The first occurrence keeps its position; later duplicates contribute their
    (already validated) citations. Order is stable. No fuzzy/semantic merging.
    """
    deduped: list[ValidatedAction] = []
    by_key: dict[tuple, ValidatedAction] = {}
    for action in actions:
        key = (
            action.action_type.value,
            action.title.strip(),
            (action.timing_text or "").strip(),
            action.due_date or "",
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = action
            deduped.append(action)
            continue
        seen = {citation.chunk_id for citation in existing.citations}
        merged = list(existing.citations)
        for citation in action.citations:
            if citation.chunk_id not in seen:
                seen.add(citation.chunk_id)
                merged.append(citation)
        if len(merged) > settings.action_max_sources_per_item:
            raise ActionValidationError(
                "An action references more sources than the configured maximum"
            )
        by_key[key] = ValidatedAction(
            action_type=existing.action_type,
            title=existing.title,
            description=existing.description,
            timing_text=existing.timing_text,
            due_date=existing.due_date,
            citations=merged,
        )
        deduped[-1] = by_key[key]
    return deduped


def _validate_action(
    provider_action,
    chunks_by_source_id: dict[str, DocumentChunk],
) -> ValidatedAction:
    try:
        action_type = ActionType(provider_action.action_type)
    except ValueError:
        raise ActionValidationError("Provider returned an invalid action type") from None

    title = (provider_action.title or "").strip()
    if not title:
        raise ActionValidationError("An action is missing a title")
    if len(title) > settings.action_max_title_length:
        raise ActionValidationError("An action title exceeds the allowed length")

    description = provider_action.description
    if description is not None:
        description = description.strip()
        if len(description) > settings.action_max_description_length:
            raise ActionValidationError("An action description exceeds the allowed length")
        if not description:
            description = None

    timing_text = provider_action.timing_text
    if timing_text is not None:
        timing_text = timing_text.strip()
        if len(timing_text) > settings.action_max_timing_length:
            raise ActionValidationError("An action timing exceeds the allowed length")
        if not timing_text:
            timing_text = None

    try:
        due_date_iso = important_date_normalized(timing_text or "", provider_action.due_date)
    except ValueError as exc:
        raise ActionValidationError(str(exc)) from exc
    due_date = date.fromisoformat(due_date_iso) if due_date_iso else None

    citations = _validate_sources(provider_action.source_ids, chunks_by_source_id)
    return ValidatedAction(
        action_type=action_type,
        title=title,
        description=description,
        timing_text=timing_text,
        due_date=due_date,
        citations=citations,
    )


def validate_provider_actions(
    provider_result: ProviderDocumentActions | None,
    chunks_by_source_id: dict[str, DocumentChunk],
) -> list[ValidatedAction]:
    if provider_result is None:
        raise ActionValidationError("Provider returned an empty action response")
    provider_actions = provider_result.actions or []
    if len(provider_actions) > settings.action_max_items:
        raise ActionValidationError("Too many actions")
    validated = [_validate_action(item, chunks_by_source_id) for item in provider_actions]
    return _dedupe_actions(validated)


def _citation_to_dict(citation: AnalysisCitation) -> dict:
    return {
        "chunk_id": citation.chunk_id,
        "page_number": citation.page_number,
        "excerpt": citation.excerpt,
    }


async def _existing_set(db: AsyncSession, document_id: uuid.UUID) -> DocumentActionSet | None:
    result = await db.execute(
        select(DocumentActionSet)
        .options(selectinload(DocumentActionSet.actions))
        .where(DocumentActionSet.document_id == document_id)
    )
    return result.scalar_one_or_none()


async def generate_actions(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: DocumentActionProvider,
) -> tuple[DocumentActionSet, bool]:
    document = await get_owned_document(db, space_id, document_id, user_id)
    if document is None:
        raise ActionNotFoundError("Document not found")
    if document.status != DocumentStatus.READY.value:
        raise ActionStateError(
            f"Document is not ready for action extraction (status: {document.status})"
        )
    chunks = await load_ordered_chunks(db, document.id)
    if not chunks:
        raise ActionStateError("Document has no chunks to analyze")

    existing = await _existing_set(db, document.id)
    if existing is not None:
        if existing.status == ActionSetStatus.PROCESSING.value:
            raise ActionConflictError("Action extraction is already in progress for this document")
        if existing.status == ActionSetStatus.READY.value:
            return existing, False

    context = build_action_context(document, chunks, settings.action_max_context_chars)
    chunks_by_source_id = {chunk_source_id(chunk): chunk for chunk in chunks}
    created = existing is None

    if existing is not None:
        action_set = existing
        action_set.status = ActionSetStatus.PROCESSING.value
        action_set.provider = settings.action_provider
        action_set.model = provider.model_name
        action_set.error_message = None
    else:
        action_set = DocumentActionSet(
            document_id=document.id,
            status=ActionSetStatus.PROCESSING.value,
            provider=settings.action_provider,
            model=provider.model_name,
        )
        db.add(action_set)
    try:
        await db.commit()
        await db.refresh(action_set)
    except IntegrityError:
        await db.rollback()
        raise ActionConflictError(
            "Action extraction is already in progress for this document"
        ) from None

    try:
        provider_result = await provider.generate_actions(context)
        validated = validate_provider_actions(provider_result, chunks_by_source_id)
        await db.execute(
            delete(DocumentAction).where(DocumentAction.action_set_id == action_set.id)
        )
        await db.flush()
        db.add_all(
            [
                DocumentAction(
                    action_set_id=action_set.id,
                    position=position,
                    action_type=action.action_type.value,
                    title=action.title,
                    description=action.description,
                    timing_text=action.timing_text,
                    due_date=action.due_date,
                    status=ActionStatus.PENDING.value,
                    sources=[_citation_to_dict(citation) for citation in action.citations],
                )
                for position, action in enumerate(validated)
            ]
        )
        action_set.status = ActionSetStatus.READY.value
        action_set.error_message = None
        await db.commit()
        fresh = await _existing_set(db, document.id)
        if fresh is None:
            raise ActionStateError("Action set could not be reloaded")
        return fresh, created
    except Exception as exc:
        await db.rollback()
        action_set.status = ActionSetStatus.FAILED.value
        action_set.error_message = str(exc)
        await db.commit()
        raise exc


async def get_document_action_set(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
) -> DocumentActionSet | None:
    document = await get_owned_document(db, space_id, document_id, user_id)
    if document is None:
        return None
    return await _existing_set(db, document.id)


async def _owned_action(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    action_id: uuid.UUID,
    user_id: uuid.UUID,
) -> DocumentAction | None:
    result = await db.execute(
        select(DocumentAction, DocumentActionSet)
        .join(DocumentActionSet, DocumentAction.action_set_id == DocumentActionSet.id)
        .join(Document, DocumentActionSet.document_id == Document.id)
        .join(KnowledgeSpace, Document.knowledge_space_id == KnowledgeSpace.id)
        .where(
            DocumentAction.id == action_id,
            Document.id == document_id,
            DocumentActionSet.document_id == document_id,
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.user_id == user_id,
        )
    )
    row = result.first()
    return row[0] if row is not None else None


async def update_action_status(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    action_id: uuid.UUID,
    user_id: uuid.UUID,
    status: ActionStatus,
) -> DocumentAction:
    action = await _owned_action(db, space_id, document_id, action_id, user_id)
    if action is None:
        raise ActionNotFoundError("Action not found")
    action.status = status.value
    action.completed_at = datetime.now(UTC) if status == ActionStatus.COMPLETED else None
    await db.commit()
    await db.refresh(action)
    return action
