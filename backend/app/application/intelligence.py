import hashlib
import json
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.analysis import load_ordered_chunks
from app.application.documents import get_owned_space
from app.application.generation_lease import complete_generation, reclaim_generation
from app.config import settings
from app.domain.analysis import AnalysisSource
from app.domain.errors import (
    IntelligenceConflictError,
    IntelligenceContextTooLargeError,
    IntelligenceNotFoundError,
    IntelligenceStateError,
    IntelligenceValidationError,
    ProviderError,
)
from app.domain.intelligence import (
    MAX_INTELLIGENCE_CONTRADICTIONS,
    MAX_INTELLIGENCE_DATES,
    MAX_INTELLIGENCE_KEY_FACTS,
    MAX_INTELLIGENCE_LABEL_LENGTH,
    MAX_INTELLIGENCE_OPEN_QUESTIONS,
    MAX_INTELLIGENCE_SUMMARY_LENGTH,
    MAX_INTELLIGENCE_VALUE_LENGTH,
    IntelligenceCitation,
    IntelligenceDocumentContext,
    IntelligenceStatus,
    ProviderContradiction,
    ProviderDate,
    ProviderKeyFact,
    ProviderOpenQuestion,
    SpaceIntelligenceContext,
    SpaceIntelligenceProvider,
    SpaceIntelligenceResult,
    ValidatedContradiction,
    ValidatedDate,
    ValidatedKeyFact,
    ValidatedOpenQuestion,
)
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    SpaceIntelligence,
)

_INTERNAL_SOURCE_LABEL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])source_\d+(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)


def space_intelligence_signature(documents: list[Document]) -> str:
    """Deterministic SHA-256 identity for the READY document state of a space.

    Hashes the sorted ``(document_id, updated_at)`` pairs so the signature
    changes exactly when the set of ready documents changes or any member's
    persisted state changes. Never uses Python's ``hash()``; the digest
    contains no raw filenames.
    """
    canonical = json.dumps(
        {
            "documents": [
                {
                    "id": str(document.id),
                    "updated_at": document.updated_at.isoformat()
                    if document.updated_at is not None
                    else "",
                }
                for document in sorted(documents, key=lambda document: str(document.id))
            ]
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def load_ready_documents(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[Document] | None:
    """Load every READY private document in the user's space (deterministic order).

    Returns ``None`` when the space is not the user's (reported as a plain 404,
    never revealing ownership). Processing/failed documents are excluded.
    """
    if await get_owned_space(db, space_id, user_id) is None:
        return None
    result = await db.execute(
        select(Document)
        .where(
            Document.knowledge_space_id == space_id,
            Document.status == DocumentStatus.READY.value,
        )
        .order_by(Document.id)
    )
    return list(result.scalars().all())


async def build_intelligence_context(
    db: AsyncSession,
    documents: list[Document],
) -> tuple[SpaceIntelligenceContext, dict[str, DocumentChunk]]:
    """Build the provider context from the full stored chunks of every READY doc.

    Documents are ordered canonically (sorted UUID); chunks within each document
    by page then chunk index. Sources are labelled ``source_1``, ``source_2``, ...
    (positional labels the model can cite verbatim) rather than raw UUIDs; the
    server maps labels back to real chunks for citation validation.
    """
    document_contexts: list[IntelligenceDocumentContext] = []
    chunks_by_source_id: dict[str, DocumentChunk] = {}
    counter = 0
    for document in documents:
        chunks = await load_ordered_chunks(db, document.id)
        if not chunks:
            raise IntelligenceStateError(
                f"Document '{document.original_filename}' has no chunks to analyze"
            )
        sources: list[AnalysisSource] = []
        for chunk in chunks:
            counter += 1
            source_id = f"source_{counter}"
            sources.append(
                AnalysisSource(
                    source_id=source_id,
                    page_number=chunk.page_number,
                    content=chunk.content,
                )
            )
            chunks_by_source_id[source_id] = chunk
        document_contexts.append(
            IntelligenceDocumentContext(
                document_id=document.id,
                title=document.original_filename,
                sources=sources,
            )
        )
    context = SpaceIntelligenceContext(documents=document_contexts)
    if context.total_chars() > settings.intelligence_max_context_chars:
        raise IntelligenceContextTooLargeError(
            "The space exceeds the supported intelligence context size; "
            f"the limit is {settings.intelligence_max_context_chars} characters"
        )
    return context, chunks_by_source_id


def _validate_citations(
    source_ids: list[str],
    chunks_by_source_id: dict[str, DocumentChunk],
    documents_by_id: dict[uuid.UUID, Document],
) -> list[IntelligenceCitation]:
    unique_ids = list(dict.fromkeys(source_ids))
    if len(unique_ids) > settings.intelligence_max_sources_per_item:
        raise IntelligenceValidationError(
            "An intelligence item references more sources than the configured maximum"
        )
    citations: list[IntelligenceCitation] = []
    for source_id in unique_ids:
        chunk = chunks_by_source_id.get(source_id)
        if chunk is None:
            raise IntelligenceValidationError(
                f"Provider referenced an unknown or unauthorized source: {source_id}"
            )
        document = documents_by_id.get(chunk.document_id)
        citations.append(
            IntelligenceCitation(
                document_id=chunk.document_id,
                document_name=document.original_filename if document is not None else "",
                chunk_id=str(chunk.id),
                page_number=chunk.page_number,
                excerpt=chunk.content[: settings.intelligence_excerpt_chars],
            )
        )
    if not citations:
        raise IntelligenceValidationError("An intelligence item has no supporting evidence")
    return citations


def _sanitize_provider_text(value: str, source_ids, field: str) -> str:
    """Remove validated positional source labels without hiding unknown labels."""
    display_text = value.strip()
    for source_id in sorted(set(source_ids), key=len, reverse=True):
        display_text = re.sub(
            rf"(?<![A-Za-z0-9_-]){re.escape(source_id)}(?![A-Za-z0-9_-])",
            "",
            display_text,
            flags=re.IGNORECASE,
        )
    display_text = re.sub(r"\(\s*\)|\[\s*\]", "", display_text)
    display_text = re.sub(r"[ \t]+([,.;:!?])", r"\1", display_text)
    display_text = re.sub(r"[ \t]+", " ", display_text).strip()
    if _INTERNAL_SOURCE_LABEL_PATTERN.search(display_text):
        raise IntelligenceValidationError(
            f"An intelligence {field} contains internal source identifiers"
        )
    return display_text


def _require_title(value: str, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise IntelligenceValidationError(f"An intelligence item is missing {field}")
    if len(text) > MAX_INTELLIGENCE_LABEL_LENGTH:
        raise IntelligenceValidationError(f"An intelligence {field} exceeds the allowed length")
    return text


def _require_value(value: str, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise IntelligenceValidationError(f"An intelligence item is missing {field}")
    if len(text) > MAX_INTELLIGENCE_VALUE_LENGTH:
        raise IntelligenceValidationError(f"An intelligence {field} exceeds the allowed length")
    return text


def _validate_fact(
    item: ProviderKeyFact,
    chunks_by_source_id: dict[str, DocumentChunk],
    documents_by_id: dict[uuid.UUID, Document],
) -> ValidatedKeyFact:
    sources = _validate_citations(item.source_ids, chunks_by_source_id, documents_by_id)
    title = _require_title(
        _sanitize_provider_text(item.title, item.source_ids, "key fact title"), "title"
    )
    detail = _require_value(
        _sanitize_provider_text(item.detail, item.source_ids, "key fact detail"), "detail"
    )
    return ValidatedKeyFact(title=title, detail=detail, sources=sources)


def _validate_contradiction(
    item: ProviderContradiction,
    chunks_by_source_id: dict[str, DocumentChunk],
    documents_by_id: dict[uuid.UUID, Document],
) -> ValidatedContradiction:
    first_sources = _validate_citations(item.first_source_ids, chunks_by_source_id, documents_by_id)
    second_sources = _validate_citations(
        item.second_source_ids, chunks_by_source_id, documents_by_id
    )
    topic = _require_title(
        _sanitize_provider_text(
            item.topic,
            [*item.first_source_ids, *item.second_source_ids],
            "contradiction topic",
        ),
        "topic",
    )
    first_claim = _require_value(
        _sanitize_provider_text(item.first_claim, item.first_source_ids, "first claim"),
        "first_claim",
    )
    second_claim = _require_value(
        _sanitize_provider_text(item.second_claim, item.second_source_ids, "second claim"),
        "second_claim",
    )
    return ValidatedContradiction(
        topic=topic,
        first_claim=first_claim,
        first_sources=first_sources,
        second_claim=second_claim,
        second_sources=second_sources,
    )


def _validate_date(
    item: ProviderDate,
    chunks_by_source_id: dict[str, DocumentChunk],
    documents_by_id: dict[uuid.UUID, Document],
) -> ValidatedDate:
    sources = _validate_citations(item.source_ids, chunks_by_source_id, documents_by_id)
    label = _require_title(
        _sanitize_provider_text(item.label, item.source_ids, "date label"), "label"
    )
    date_text = _require_value(
        _sanitize_provider_text(item.date_text, item.source_ids, "date value"), "date_text"
    )
    context = _sanitize_provider_text(item.context or "", item.source_ids, "date context")
    if len(context) > MAX_INTELLIGENCE_VALUE_LENGTH:
        raise IntelligenceValidationError("An intelligence date context exceeds the allowed length")
    return ValidatedDate(label=label, date_text=date_text, context=context, sources=sources)


def _validate_open_question(
    item: ProviderOpenQuestion,
    chunks_by_source_id: dict[str, DocumentChunk],
    documents_by_id: dict[uuid.UUID, Document],
) -> ValidatedOpenQuestion:
    sources = (
        _validate_citations(item.source_ids, chunks_by_source_id, documents_by_id)
        if item.source_ids
        else []
    )
    question = _require_title(
        _sanitize_provider_text(item.question, item.source_ids, "open question"), "question"
    )
    explanation = _sanitize_provider_text(
        item.explanation or "", item.source_ids, "open question explanation"
    )
    if len(explanation) > MAX_INTELLIGENCE_VALUE_LENGTH:
        raise IntelligenceValidationError("An open question explanation exceeds the allowed length")
    return ValidatedOpenQuestion(question=question, explanation=explanation, sources=sources)


def validate_provider_intelligence(
    provider_result,
    documents_by_id: dict[uuid.UUID, Document],
    chunks_by_source_id: dict[str, DocumentChunk],
) -> SpaceIntelligenceResult:
    if provider_result is None:
        raise IntelligenceValidationError("Provider returned an empty intelligence result")
    summary = _sanitize_provider_text(
        provider_result.summary or "", chunks_by_source_id.keys(), "summary"
    )
    if len(summary) > MAX_INTELLIGENCE_SUMMARY_LENGTH:
        raise IntelligenceValidationError("Intelligence summary exceeds the allowed length")

    key_facts = provider_result.key_facts or []
    contradictions = provider_result.contradictions or []
    dates = provider_result.dates or []
    open_questions = provider_result.open_questions or []
    if len(key_facts) > MAX_INTELLIGENCE_KEY_FACTS:
        raise IntelligenceValidationError("Too many key facts")
    if len(contradictions) > MAX_INTELLIGENCE_CONTRADICTIONS:
        raise IntelligenceValidationError("Too many contradictions")
    if len(dates) > MAX_INTELLIGENCE_DATES:
        raise IntelligenceValidationError("Too many dates")
    if len(open_questions) > MAX_INTELLIGENCE_OPEN_QUESTIONS:
        raise IntelligenceValidationError("Too many open questions")

    return SpaceIntelligenceResult(
        summary=summary,
        key_facts=[
            _validate_fact(item, chunks_by_source_id, documents_by_id) for item in key_facts
        ],
        contradictions=[
            _validate_contradiction(item, chunks_by_source_id, documents_by_id)
            for item in contradictions
        ],
        dates=[_validate_date(item, chunks_by_source_id, documents_by_id) for item in dates],
        open_questions=[
            _validate_open_question(item, chunks_by_source_id, documents_by_id)
            for item in open_questions
        ],
    )


def _citation_to_dict(citation: IntelligenceCitation) -> dict:
    return {
        "document_id": str(citation.document_id),
        "document_name": citation.document_name,
        "chunk_id": citation.chunk_id,
        "page_number": citation.page_number,
        "excerpt": citation.excerpt,
    }


def _fact_to_dict(item: ValidatedKeyFact) -> dict:
    return {
        "title": item.title,
        "detail": item.detail,
        "sources": [_citation_to_dict(source) for source in item.sources],
    }


def _contradiction_to_dict(item: ValidatedContradiction) -> dict:
    return {
        "topic": item.topic,
        "first_claim": item.first_claim,
        "first_sources": [_citation_to_dict(source) for source in item.first_sources],
        "second_claim": item.second_claim,
        "second_sources": [_citation_to_dict(source) for source in item.second_sources],
    }


def _date_to_dict(item: ValidatedDate) -> dict:
    return {
        "label": item.label,
        "date_text": item.date_text,
        "context": item.context,
        "sources": [_citation_to_dict(source) for source in item.sources],
    }


def _open_question_to_dict(item: ValidatedOpenQuestion) -> dict:
    return {
        "question": item.question,
        "explanation": item.explanation,
        "sources": [_citation_to_dict(source) for source in item.sources],
    }


async def _existing_intelligence(
    db: AsyncSession,
    space_id: uuid.UUID,
) -> SpaceIntelligence | None:
    result = await db.execute(
        select(SpaceIntelligence)
        .execution_options(populate_existing=True)
        .where(SpaceIntelligence.knowledge_space_id == space_id)
    )
    return result.scalar_one_or_none()


async def refresh_intelligence(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: SpaceIntelligenceProvider,
) -> tuple[SpaceIntelligence, bool]:
    documents = await load_ready_documents(db, space_id, user_id)
    if documents is None:
        raise IntelligenceNotFoundError("Space not found")
    if not documents:
        raise IntelligenceStateError("No ready documents to analyze")
    if len(documents) > settings.intelligence_max_documents:
        raise IntelligenceStateError(
            f"Too many ready documents to analyze; the limit is "
            f"{settings.intelligence_max_documents}"
        )

    signature = space_intelligence_signature(documents)
    existing = await _existing_intelligence(db, space_id)
    if (
        existing is not None
        and existing.status == IntelligenceStatus.READY.value
        and existing.input_signature == signature
    ):
        return existing, False

    context, chunks_by_source_id = await build_intelligence_context(db, documents)
    return await _generate_intelligence(
        db, space_id, documents, signature, context, chunks_by_source_id, existing, provider
    )


async def _generate_intelligence(
    db: AsyncSession,
    space_id: uuid.UUID,
    documents: list[Document],
    signature: str,
    context: SpaceIntelligenceContext,
    chunks_by_source_id: dict[str, DocumentChunk],
    existing: SpaceIntelligence | None,
    provider: SpaceIntelligenceProvider,
) -> tuple[SpaceIntelligence, bool]:
    if existing is None:
        attempt_id = uuid.uuid4()
        intelligence = SpaceIntelligence(
            knowledge_space_id=space_id,
            status=IntelligenceStatus.PROCESSING.value,
            input_signature=signature,
            provider=settings.intelligence_provider,
            model=provider.model_name,
            processing_started_at=datetime.now(UTC),
            processing_attempt_id=attempt_id,
        )
        db.add(intelligence)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            reloaded = await _existing_intelligence(db, space_id)
            if reloaded is not None and reloaded.status == IntelligenceStatus.READY.value:
                return reloaded, False
            raise IntelligenceConflictError(
                "Intelligence generation is already in progress for this space"
            ) from None
        created = True
    else:
        claim = await reclaim_generation(
            db,
            SpaceIntelligence,
            existing.id,
            provider=settings.intelligence_provider,
            model_name=provider.model_name,
        )
        if claim is None:
            reloaded = await _existing_intelligence(db, space_id)
            if reloaded is not None and reloaded.status == IntelligenceStatus.READY.value:
                return reloaded, False
            raise IntelligenceConflictError(
                "Intelligence generation is already in progress for this space"
            )
        attempt_id, _ = claim
        intelligence = existing
        created = False

    intelligence_id = intelligence.id
    documents_by_id = {document.id: document for document in documents}
    try:
        provider_result = await provider.analyze(context)
        trusted = validate_provider_intelligence(
            provider_result, documents_by_id, chunks_by_source_id
        )
    except (ProviderError, IntelligenceValidationError) as exc:
        if not await complete_generation(
            db,
            SpaceIntelligence,
            intelligence_id,
            attempt_id,
            status=IntelligenceStatus.FAILED.value,
            values={"error_message": str(exc)},
        ):
            reloaded = await _existing_intelligence(db, space_id)
            if reloaded is not None and reloaded.status == IntelligenceStatus.READY.value:
                return reloaded, False
            raise IntelligenceConflictError(
                "Intelligence generation is already in progress for this space"
            ) from None
        await db.refresh(intelligence)
        raise exc

    if not await complete_generation(
        db,
        SpaceIntelligence,
        intelligence_id,
        attempt_id,
        status=IntelligenceStatus.READY.value,
        values={
            "summary": trusted.summary,
            "key_facts": [_fact_to_dict(item) for item in trusted.key_facts],
            "contradictions": [_contradiction_to_dict(item) for item in trusted.contradictions],
            "dates": [_date_to_dict(item) for item in trusted.dates],
            "open_questions": [_open_question_to_dict(item) for item in trusted.open_questions],
            "error_message": None,
        },
    ):
        reloaded = await _existing_intelligence(db, space_id)
        if reloaded is not None and reloaded.status == IntelligenceStatus.READY.value:
            return reloaded, False
        raise IntelligenceConflictError(
            "Intelligence generation is already in progress for this space"
        )

    reloaded = await _existing_intelligence(db, space_id)
    if reloaded is None:
        raise IntelligenceStateError("Intelligence could not be reloaded")
    return reloaded, created


async def get_intelligence_state(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[list[Document] | None, SpaceIntelligence | None, str | None, bool]:
    """Return (ready_documents, snapshot, current_signature, is_stale).

    ``ready_documents`` is ``None`` when the space is not the user's. ``is_stale``
    is true only when a READY snapshot's signature no longer matches the current
    ready-document state.
    """
    documents = await load_ready_documents(db, space_id, user_id)
    if documents is None:
        return None, None, None, False
    current_signature = space_intelligence_signature(documents) if documents else None
    snapshot = await _existing_intelligence(db, space_id)
    is_stale = bool(
        snapshot is not None
        and snapshot.status == IntelligenceStatus.READY.value
        and snapshot.input_signature != current_signature
    )
    return documents, snapshot, current_signature, is_stale
