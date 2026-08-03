import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.documents import get_owned_document
from app.config import settings
from app.domain.analysis import (
    AnalysisCitation,
    AnalysisSource,
    DocumentAnalysisContext,
    DocumentAnalysisProvider,
    DocumentAnalysisResult,
    ProviderKeyFact,
    ValidatedImportantDate,
    ValidatedKeyFact,
    parse_document_type,
)
from app.domain.errors import (
    AnalysisConflictError,
    AnalysisContextTooLargeError,
    AnalysisNotFoundError,
    AnalysisStateError,
    AnalysisValidationError,
    ProviderError,
)
from app.infrastructure.analysis_providers import important_date_normalized
from app.infrastructure.models import (
    Document,
    DocumentAnalysis,
    DocumentAnalysisStatus,
    DocumentChunk,
    DocumentStatus,
)


def chunk_source_id(chunk: DocumentChunk) -> str:
    return f"chunk:{chunk.id}"


async def load_ordered_chunks(
    db: AsyncSession,
    document_id: uuid.UUID,
) -> list[DocumentChunk]:
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.page_number, DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


def build_context(
    document: Document,
    chunks: list[DocumentChunk],
    max_context_chars: int,
) -> DocumentAnalysisContext:
    sources = [
        AnalysisSource(
            source_id=chunk_source_id(chunk),
            page_number=chunk.page_number,
            content=chunk.content,
        )
        for chunk in chunks
    ]
    context = DocumentAnalysisContext(document_id=document.id, sources=sources)
    if len(context.render()) > max_context_chars:
        raise AnalysisContextTooLargeError(
            "Document exceeds the supported analysis context size; "
            f"the limit is {max_context_chars} characters"
        )
    return context


def _validate_citation_sources(
    source_ids: list[str],
    chunks_by_source_id: dict[str, DocumentChunk],
) -> list[AnalysisCitation]:
    unique_ids = list(dict.fromkeys(source_ids))
    if len(unique_ids) > settings.analysis_max_sources_per_item:
        raise AnalysisValidationError(
            "An analysis item references more sources than the configured maximum"
        )
    citations: list[AnalysisCitation] = []
    for source_id in unique_ids:
        chunk = chunks_by_source_id.get(source_id)
        if chunk is None:
            raise AnalysisValidationError(
                f"Provider referenced an unknown or unauthorized source: {source_id}"
            )
        citations.append(
            AnalysisCitation(
                chunk_id=str(chunk.id),
                page_number=chunk.page_number,
                excerpt=chunk.content[: settings.analysis_excerpt_chars],
            )
        )
    if not citations:
        raise AnalysisValidationError("An analysis item has no supporting evidence")
    return citations


def _validate_date(
    item,
    chunks_by_source_id: dict[str, DocumentChunk],
) -> ValidatedImportantDate:
    label = item.label.strip()
    value = item.value.strip()
    if not label:
        raise AnalysisValidationError("An important date is missing a label")
    if len(label) > settings.analysis_max_label_length:
        raise AnalysisValidationError("An important date label exceeds the allowed length")
    if not value:
        raise AnalysisValidationError("An important date is missing a value")
    if len(value) > settings.analysis_max_value_length:
        raise AnalysisValidationError("An important date value exceeds the allowed length")
    try:
        normalized_date = important_date_normalized(value, item.normalized_date)
    except ValueError as exc:
        raise AnalysisValidationError(str(exc)) from exc
    sources = _validate_citation_sources(item.source_ids, chunks_by_source_id)
    return ValidatedImportantDate(
        label=label,
        value=value,
        normalized_date=normalized_date,
        sources=sources,
    )


def _validate_fact(
    item: ProviderKeyFact,
    chunks_by_source_id: dict[str, DocumentChunk],
) -> ValidatedKeyFact:
    label = item.label.strip()
    value = item.value.strip()
    if not label:
        raise AnalysisValidationError("A key fact is missing a label")
    if len(label) > settings.analysis_max_label_length:
        raise AnalysisValidationError("A key fact label exceeds the allowed length")
    if not value:
        raise AnalysisValidationError("A key fact is missing a value")
    if len(value) > settings.analysis_max_value_length:
        raise AnalysisValidationError("A key fact value exceeds the allowed length")
    sources = _validate_citation_sources(item.source_ids, chunks_by_source_id)
    return ValidatedKeyFact(label=label, value=value, sources=sources)


def validate_provider_analysis(
    provider_result,
    chunks_by_source_id: dict[str, DocumentChunk],
) -> DocumentAnalysisResult:
    if provider_result is None:
        raise AnalysisValidationError("Provider returned an empty analysis")
    document_type = parse_document_type(getattr(provider_result, "document_type", None))
    normalized_title = (provider_result.normalized_title or "").strip()
    summary = (provider_result.summary or "").strip()
    if not normalized_title:
        raise AnalysisValidationError("Provider did not return a normalized title")
    if len(normalized_title) > 500:
        raise AnalysisValidationError("Normalized title exceeds the allowed length")
    if len(summary) > settings.analysis_max_summary_length:
        raise AnalysisValidationError("Summary exceeds the allowed length")
    important_dates = provider_result.important_dates or []
    key_facts = provider_result.key_facts or []
    if len(important_dates) > settings.analysis_max_important_dates:
        raise AnalysisValidationError("Too many important dates")
    if len(key_facts) > settings.analysis_max_key_facts:
        raise AnalysisValidationError("Too many key facts")
    dates = [_validate_date(item, chunks_by_source_id) for item in important_dates]
    facts = [_validate_fact(item, chunks_by_source_id) for item in key_facts]
    return DocumentAnalysisResult(
        document_type=document_type,
        normalized_title=normalized_title,
        summary=summary,
        important_dates=dates,
        key_facts=facts,
    )


def _citation_to_dict(citation: AnalysisCitation) -> dict:
    return {
        "chunk_id": citation.chunk_id,
        "page_number": citation.page_number,
        "excerpt": citation.excerpt,
    }


def _date_to_dict(item: ValidatedImportantDate) -> dict:
    return {
        "label": item.label,
        "value": item.value,
        "normalized_date": item.normalized_date,
        "sources": [_citation_to_dict(source) for source in item.sources],
    }


def _fact_to_dict(item: ValidatedKeyFact) -> dict:
    return {
        "label": item.label,
        "value": item.value,
        "sources": [_citation_to_dict(source) for source in item.sources],
    }


async def _existing_analysis(db: AsyncSession, document_id: uuid.UUID) -> DocumentAnalysis | None:
    result = await db.execute(
        select(DocumentAnalysis).where(DocumentAnalysis.document_id == document_id)
    )
    return result.scalar_one_or_none()


async def analyze_document(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: DocumentAnalysisProvider,
) -> tuple[DocumentAnalysis, bool]:
    document = await get_owned_document(db, space_id, document_id, user_id)
    if document is None:
        raise AnalysisNotFoundError("Document not found")
    if document.status != DocumentStatus.READY.value:
        raise AnalysisStateError(f"Document is not ready for analysis (status: {document.status})")
    chunks = await load_ordered_chunks(db, document.id)
    if not chunks:
        raise AnalysisStateError("Document has no chunks to analyze")

    existing = await _existing_analysis(db, document.id)
    if existing is not None:
        if existing.status == DocumentAnalysisStatus.PROCESSING.value:
            raise AnalysisConflictError("An analysis is already in progress for this document")
        if existing.status == DocumentAnalysisStatus.READY.value:
            return existing, False

    context = build_context(document, chunks, settings.analysis_max_context_chars)
    chunks_by_source_id = {chunk_source_id(chunk): chunk for chunk in chunks}
    created = existing is None

    if existing is not None:
        analysis = existing
        analysis.status = DocumentAnalysisStatus.PROCESSING.value
        analysis.provider = settings.analysis_provider
        analysis.model = provider.model_name
        analysis.error_message = None
    else:
        analysis = DocumentAnalysis(
            document_id=document.id,
            status=DocumentAnalysisStatus.PROCESSING.value,
            provider=settings.analysis_provider,
            model=provider.model_name,
        )
        db.add(analysis)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AnalysisConflictError(
            "An analysis is already in progress for this document"
        ) from None

    try:
        provider_result = await provider.analyze(context)
        trusted = validate_provider_analysis(provider_result, chunks_by_source_id)
        analysis.document_type = trusted.document_type.value
        analysis.normalized_title = trusted.normalized_title
        analysis.summary = trusted.summary
        analysis.important_dates = [_date_to_dict(item) for item in trusted.important_dates]
        analysis.key_facts = [_fact_to_dict(item) for item in trusted.key_facts]
        analysis.status = DocumentAnalysisStatus.READY.value
        analysis.error_message = None
        await db.commit()
        await db.refresh(analysis)
        return analysis, created
    except (ProviderError, AnalysisValidationError) as exc:
        await db.rollback()
        analysis.status = DocumentAnalysisStatus.FAILED.value
        analysis.error_message = str(exc)
        await db.commit()
        raise exc


async def get_document_analysis(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
) -> DocumentAnalysis | None:
    document = await get_owned_document(db, space_id, document_id, user_id)
    if document is None:
        return None
    return await _existing_analysis(db, document.id)
