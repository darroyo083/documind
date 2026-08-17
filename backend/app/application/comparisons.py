import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.analysis import load_ordered_chunks
from app.application.documents import get_owned_space
from app.application.generation_lease import claim_generation, complete_generation
from app.config import settings
from app.domain.analysis import AnalysisSource
from app.domain.comparison import (
    MAX_COMPARISON_COMMONALITIES,
    MAX_COMPARISON_DESCRIPTION_LENGTH,
    MAX_COMPARISON_DIMENSIONS,
    MAX_COMPARISON_DOCUMENTS,
    MAX_COMPARISON_KEY_DIFFERENCES,
    MAX_COMPARISON_LABEL_LENGTH,
    MAX_COMPARISON_SUMMARY_LENGTH,
    MAX_COMPARISON_SYNTHESIS_LENGTH,
    MAX_COMPARISON_TITLE_LENGTH,
    MAX_COMPARISON_VALUE_LENGTH,
    MIN_COMPARISON_DOCUMENTS,
    ComparisonCitation,
    ComparisonDocumentContext,
    ComparisonResult,
    ComparisonStatus,
    DocumentComparisonContext,
    DocumentComparisonProvider,
    ProviderComparisonResult,
    ValidatedCommonality,
    ValidatedComparisonDimension,
    ValidatedComparisonFinding,
    ValidatedKeyDifference,
    parse_document_ref,
)
from app.domain.errors import (
    ComparisonConflictError,
    ComparisonContextTooLargeError,
    ComparisonNotFoundError,
    ComparisonStateError,
    ComparisonValidationError,
    ProviderError,
)
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    DocumentComparison,
    DocumentComparisonDocument,
    DocumentStatus,
    KnowledgeSpace,
)

logger = logging.getLogger(__name__)

_MEMBER_LOAD = selectinload(DocumentComparison.members).joinedload(
    DocumentComparisonDocument.document
)


def normalize_focus(focus: str | None) -> str | None:
    """Trim and collapse whitespace; empty/whitespace-only focus becomes null.

    The same normalized value is used for the persisted focus and the
    comparison signature so identity never depends on formatting. Unicode is
    preserved.
    """
    if focus is None:
        return None
    normalized = " ".join(focus.split())
    return normalized or None


def comparison_signature(document_ids: list[uuid.UUID], focus: str | None) -> str:
    """Deterministic SHA-256 identity for a comparison request.

    Canonicalizes the document set (sorted UUID strings) and the normalized
    focus, so ``[A, B]`` and ``[B, A]`` with the same focus resolve to the same
    comparison while a different focus yields a different one. Never uses
    Python's hash(); the digest contains no raw document names or focus text.

    The canonical bytes are a structured JSON object (sorted keys, compact
    separators) rather than delimiter concatenation, so document IDs and focus
    text cannot collide at serialization boundaries: distinct
    (document-set, focus) pairs always produce distinct canonical bytes.
    """
    canonical = json.dumps(
        {
            "documents": sorted(str(document_id) for document_id in document_ids),
            "focus": normalize_focus(focus),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def chunk_source_id(chunk: DocumentChunk) -> str:
    return f"chunk:{chunk.id}"


async def load_owned_documents(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    user_id: uuid.UUID,
) -> list[Document] | None:
    """Load the selected documents only when every one is owned and in the space.

    Returns ``None`` when the space is not the user's or any selected document
    is missing, which the API reports as a plain 404 — never revealing which
    arbitrary document ID belongs to another user or space.
    """
    if await get_owned_space(db, space_id, user_id) is None:
        return None
    result = await db.execute(
        select(Document).where(
            Document.id.in_(document_ids),
            Document.knowledge_space_id == space_id,
        )
    )
    documents = list(result.scalars().all())
    if len(documents) != len(set(document_ids)):
        return None
    documents.sort(key=lambda document: str(document.id))
    return documents


async def build_comparison_context(
    db: AsyncSession,
    documents: list[Document],
    focus: str | None,
) -> tuple[DocumentComparisonContext, dict[str, DocumentChunk]]:
    """Build the provider context from the full stored chunks of every document.

    Documents are ordered canonically (sorted UUID), chunks within each
    document are ordered by page then chunk index. No semantic retrieval, no
    re-extraction, no re-embedding, no reference corpus: the provider sees only
    the selected documents' persisted chunks. Returns the context plus the
    source-id → chunk map used for citation validation.
    """
    contexts = []
    chunks_by_source_id: dict[str, DocumentChunk] = {}
    for position, document in enumerate(documents, start=1):
        chunks = await load_ordered_chunks(db, document.id)
        if not chunks:
            raise ComparisonStateError(
                f"Document '{document.original_filename}' has no chunks to compare"
            )
        contexts.append(_document_context(position, document, chunks))
        for chunk in chunks:
            chunks_by_source_id[chunk_source_id(chunk)] = chunk
    context = DocumentComparisonContext(documents=contexts, focus=focus)
    if context.total_chars() > settings.comparison_max_context_chars:
        raise ComparisonContextTooLargeError(
            "The selected documents exceed the supported comparison context size; "
            f"the limit is {settings.comparison_max_context_chars} characters"
        )
    return context, chunks_by_source_id


def _document_context(
    position: int,
    document: Document,
    chunks: list[DocumentChunk],
) -> ComparisonDocumentContext:
    return ComparisonDocumentContext(
        position=position,
        document_id=document.id,
        title=document.original_filename,
        sources=[
            AnalysisSource(
                source_id=chunk_source_id(chunk),
                page_number=chunk.page_number,
                content=chunk.content,
            )
            for chunk in chunks
        ],
    )


def _validate_citations(
    source_ids: list[str],
    chunks_by_source_id: dict[str, DocumentChunk],
) -> list[ComparisonCitation]:
    unique_ids = list(dict.fromkeys(source_ids))
    if len(unique_ids) > settings.comparison_max_sources_per_item:
        raise ComparisonValidationError(
            "A comparison item references more sources than the configured maximum"
        )
    citations: list[ComparisonCitation] = []
    for source_id in unique_ids:
        canonical_source_id = source_id
        if canonical_source_id not in chunks_by_source_id:
            prefixed_source_id = f"chunk:{source_id}"
            if prefixed_source_id in chunks_by_source_id:
                canonical_source_id = prefixed_source_id
        chunk = chunks_by_source_id.get(canonical_source_id)
        if chunk is None:
            raise ComparisonValidationError(
                f"Provider referenced an unknown or unauthorized source: {source_id}"
            )
        citations.append(
            ComparisonCitation(
                document_id=chunk.document_id,
                chunk_id=str(chunk.id),
                page_number=chunk.page_number,
                excerpt=chunk.content[: settings.comparison_excerpt_chars],
            )
        )
    if not citations:
        raise ComparisonValidationError("A comparison item has no supporting evidence")
    return citations


def _validate_finding(
    finding,
    documents_by_position: dict[int, Document],
    chunks_by_source_id: dict[str, DocumentChunk],
) -> ValidatedComparisonFinding:
    position = parse_document_ref(getattr(finding, "document_ref", None))
    document = documents_by_position.get(position) if position is not None else None
    if document is None:
        raise ComparisonValidationError("Provider referenced an unknown document")
    if finding.not_identified:
        if finding.source_ids:
            raise ComparisonValidationError("A not-identified finding must not cite sources")
        return ValidatedComparisonFinding(
            document_id=document.id,
            value=None,
            not_identified=True,
        )
    value = (finding.value or "").strip()
    if not value:
        raise ComparisonValidationError("A finding is missing a value")
    if len(value) > MAX_COMPARISON_VALUE_LENGTH:
        raise ComparisonValidationError("A finding value exceeds the allowed length")
    citations = _validate_citations(finding.source_ids, chunks_by_source_id)
    if any(citation.document_id != document.id for citation in citations):
        raise ComparisonValidationError("A finding must cite evidence from its own document")
    return ValidatedComparisonFinding(
        document_id=document.id,
        value=value,
        not_identified=False,
        sources=citations,
    )


def _validate_dimension(
    dimension,
    documents_by_position: dict[int, Document],
    chunks_by_source_id: dict[str, DocumentChunk],
) -> ValidatedComparisonDimension:
    label = (dimension.label or "").strip()
    if not label:
        raise ComparisonValidationError("A comparison dimension is missing a label")
    if len(label) > MAX_COMPARISON_LABEL_LENGTH:
        raise ComparisonValidationError("A comparison dimension label exceeds the allowed length")

    provider_findings = dimension.findings or []
    positions = [
        parse_document_ref(getattr(finding, "document_ref", None)) for finding in provider_findings
    ]
    expected_positions = set(documents_by_position)
    if any(position is None for position in positions):
        raise ComparisonValidationError("A dimension references an unknown document")
    if len(set(positions)) != len(positions):
        raise ComparisonValidationError("A dimension contains duplicate document findings")
    if set(positions) != expected_positions:
        logger.warning(
            "Comparison dimension document refs did not cover selected documents label=%s "
            "positions=%s expected=%s",
            label,
            positions,
            sorted(expected_positions),
        )
        raise ComparisonValidationError(
            "A dimension must contain exactly one finding per selected document"
        )

    findings = [
        _validate_finding(finding, documents_by_position, chunks_by_source_id)
        for finding in provider_findings
    ]

    synthesis = dimension.synthesis
    if synthesis is not None:
        synthesis = synthesis.strip()
        if len(synthesis) > MAX_COMPARISON_SYNTHESIS_LENGTH:
            raise ComparisonValidationError("A dimension synthesis exceeds the allowed length")
        if not synthesis:
            synthesis = None

    sources = (
        _validate_citations(dimension.source_ids, chunks_by_source_id)
        if dimension.source_ids
        else []
    )
    return ValidatedComparisonDimension(
        label=label,
        findings=findings,
        synthesis=synthesis,
        sources=sources,
    )


def _validate_difference(
    item,
    chunks_by_source_id: dict[str, DocumentChunk],
) -> ValidatedKeyDifference:
    title = (item.title or "").strip()
    if not title:
        raise ComparisonValidationError("A key difference is missing a title")
    if len(title) > MAX_COMPARISON_LABEL_LENGTH:
        raise ComparisonValidationError("A key difference title exceeds the allowed length")
    description = (item.description or "").strip()
    if not description:
        raise ComparisonValidationError("A key difference is missing a description")
    if len(description) > MAX_COMPARISON_DESCRIPTION_LENGTH:
        raise ComparisonValidationError("A key difference description exceeds the allowed length")
    citations = _validate_citations(item.source_ids, chunks_by_source_id)
    if len({citation.document_id for citation in citations}) < 2:
        raise ComparisonValidationError(
            "A key difference must cite evidence from at least two documents"
        )
    return ValidatedKeyDifference(title=title, description=description, sources=citations)


def _validate_commonality(
    item,
    chunks_by_source_id: dict[str, DocumentChunk],
) -> ValidatedCommonality:
    title = (item.title or "").strip()
    if not title:
        raise ComparisonValidationError("A commonality is missing a title")
    if len(title) > MAX_COMPARISON_LABEL_LENGTH:
        raise ComparisonValidationError("A commonality title exceeds the allowed length")
    description = (item.description or "").strip()
    if not description:
        raise ComparisonValidationError("A commonality is missing a description")
    if len(description) > MAX_COMPARISON_DESCRIPTION_LENGTH:
        raise ComparisonValidationError("A commonality description exceeds the allowed length")
    citations = _validate_citations(item.source_ids, chunks_by_source_id)
    if len({citation.document_id for citation in citations}) < 2:
        raise ComparisonValidationError(
            "A commonality must cite evidence from at least two documents"
        )
    return ValidatedCommonality(title=title, description=description, sources=citations)


def validate_provider_comparison(
    provider_result: ProviderComparisonResult | None,
    documents: list[Document],
    chunks_by_source_id: dict[str, DocumentChunk],
) -> ComparisonResult:
    if provider_result is None:
        raise ComparisonValidationError("Provider returned an empty comparison")

    title = (provider_result.title or "").strip()
    if not title:
        raise ComparisonValidationError("Provider did not return a comparison title")
    if len(title) > MAX_COMPARISON_TITLE_LENGTH:
        raise ComparisonValidationError("Comparison title exceeds the allowed length")

    summary = (provider_result.summary or "").strip()
    if len(summary) > MAX_COMPARISON_SUMMARY_LENGTH:
        raise ComparisonValidationError("Summary exceeds the allowed length")

    provider_dimensions = provider_result.dimensions or []
    if not 1 <= len(provider_dimensions) <= MAX_COMPARISON_DIMENSIONS:
        raise ComparisonValidationError(
            f"A comparison must contain between 1 and {MAX_COMPARISON_DIMENSIONS} dimensions"
        )
    provider_differences = provider_result.key_differences or []
    if len(provider_differences) > MAX_COMPARISON_KEY_DIFFERENCES:
        raise ComparisonValidationError("Too many key differences")
    provider_commonalities = provider_result.commonalities or []
    if len(provider_commonalities) > MAX_COMPARISON_COMMONALITIES:
        raise ComparisonValidationError("Too many commonalities")

    documents_by_position = {
        position: document for position, document in enumerate(documents, start=1)
    }
    dimensions = [
        _validate_dimension(dimension, documents_by_position, chunks_by_source_id)
        for dimension in provider_dimensions
    ]
    differences = [_validate_difference(item, chunks_by_source_id) for item in provider_differences]
    commonalities = [
        _validate_commonality(item, chunks_by_source_id) for item in provider_commonalities
    ]
    return ComparisonResult(
        title=title,
        summary=summary,
        dimensions=dimensions,
        key_differences=differences,
        commonalities=commonalities,
    )


def _citation_to_dict(citation: ComparisonCitation) -> dict:
    return {
        "document_id": str(citation.document_id),
        "chunk_id": citation.chunk_id,
        "page_number": citation.page_number,
        "excerpt": citation.excerpt,
    }


def _finding_to_dict(finding: ValidatedComparisonFinding) -> dict:
    return {
        "document_id": str(finding.document_id),
        "value": finding.value,
        "not_identified": finding.not_identified,
        "sources": [_citation_to_dict(citation) for citation in finding.sources],
    }


def _dimension_to_dict(dimension: ValidatedComparisonDimension) -> dict:
    return {
        "label": dimension.label,
        "findings": [_finding_to_dict(finding) for finding in dimension.findings],
        "synthesis": dimension.synthesis,
        "sources": [_citation_to_dict(citation) for citation in dimension.sources],
    }


def _difference_to_dict(item: ValidatedKeyDifference) -> dict:
    return {
        "title": item.title,
        "description": item.description,
        "sources": [_citation_to_dict(citation) for citation in item.sources],
    }


def _commonality_to_dict(item: ValidatedCommonality) -> dict:
    return {
        "title": item.title,
        "description": item.description,
        "sources": [_citation_to_dict(citation) for citation in item.sources],
    }


async def _comparison_by_signature(
    db: AsyncSession,
    space_id: uuid.UUID,
    signature: str,
) -> DocumentComparison | None:
    result = await db.execute(
        select(DocumentComparison)
        .options(_MEMBER_LOAD)
        .execution_options(populate_existing=True)
        .where(
            DocumentComparison.knowledge_space_id == space_id,
            DocumentComparison.comparison_signature == signature,
        )
    )
    return result.scalar_one_or_none()


async def create_comparison(
    db: AsyncSession,
    space_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    focus: str | None,
    user_id: uuid.UUID,
    provider: DocumentComparisonProvider,
) -> tuple[DocumentComparison, bool]:
    if not MIN_COMPARISON_DOCUMENTS <= len(document_ids) <= MAX_COMPARISON_DOCUMENTS:
        raise ComparisonStateError(
            "Select between "
            f"{MIN_COMPARISON_DOCUMENTS} and {MAX_COMPARISON_DOCUMENTS} documents to compare"
        )
    if len(set(document_ids)) != len(document_ids):
        raise ComparisonStateError("The selected documents must be unique")

    normalized_focus = normalize_focus(focus)
    if (
        normalized_focus is not None
        and len(normalized_focus) > settings.comparison_max_focus_length
    ):
        raise ComparisonStateError(
            "Comparison focus must be no longer than "
            f"{settings.comparison_max_focus_length} characters"
        )

    documents = await load_owned_documents(db, space_id, document_ids, user_id)
    if documents is None:
        raise ComparisonNotFoundError("Documents not found")
    if any(document.status != DocumentStatus.READY.value for document in documents):
        raise ComparisonStateError("All selected documents must be ready for comparison")

    signature = comparison_signature(document_ids, normalized_focus)

    existing = await _comparison_by_signature(db, space_id, signature)
    if existing is not None and existing.status == ComparisonStatus.READY.value:
        return existing, False

    context, chunks_by_source_id = await build_comparison_context(db, documents, normalized_focus)
    return await _generate_comparison(
        db,
        space_id,
        documents,
        signature,
        normalized_focus,
        context,
        chunks_by_source_id,
        existing,
        provider,
    )


async def _generate_comparison(
    db: AsyncSession,
    space_id: uuid.UUID,
    documents: list[Document],
    signature: str,
    normalized_focus: str | None,
    context: DocumentComparisonContext,
    chunks_by_source_id: dict[str, DocumentChunk],
    existing: DocumentComparison | None,
    provider: DocumentComparisonProvider,
) -> tuple[DocumentComparison, bool]:
    if existing is None:
        attempt_id = uuid.uuid4()
        comparison = DocumentComparison(
            knowledge_space_id=space_id,
            status=ComparisonStatus.PROCESSING.value,
            comparison_signature=signature,
            focus=normalized_focus,
            provider=settings.comparison_provider,
            model=provider.model_name,
            processing_started_at=datetime.now(UTC),
            processing_attempt_id=attempt_id,
            members=[
                DocumentComparisonDocument(
                    document_id=document.id,
                    position=position,
                )
                for position, document in enumerate(documents)
            ],
        )
        db.add(comparison)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            reloaded = await _comparison_by_signature(db, space_id, signature)
            if reloaded is not None and reloaded.status == ComparisonStatus.READY.value:
                return reloaded, False
            raise ComparisonConflictError(
                "A comparison is already in progress for these documents"
            ) from None
        created = True
    else:
        claim = await claim_generation(
            db,
            DocumentComparison,
            existing.id,
            provider=settings.comparison_provider,
            model_name=provider.model_name,
        )
        if claim is None:
            reloaded = await _comparison_by_signature(db, space_id, signature)
            if reloaded is not None and reloaded.status == ComparisonStatus.READY.value:
                return reloaded, False
            raise ComparisonConflictError("A comparison is already in progress for these documents")
        attempt_id, _ = claim
        comparison = existing
        created = False

    comparison_id = comparison.id
    try:
        provider_result = await provider.compare(context)
        trusted = validate_provider_comparison(provider_result, documents, chunks_by_source_id)
    except (ProviderError, ComparisonValidationError) as exc:
        if not await complete_generation(
            db,
            DocumentComparison,
            comparison_id,
            attempt_id,
            status=ComparisonStatus.FAILED.value,
            values={"error_message": str(exc)},
        ):
            reloaded = await _comparison_by_signature(db, space_id, signature)
            if reloaded is not None and reloaded.status == ComparisonStatus.READY.value:
                return reloaded, False
            raise ComparisonConflictError(
                "A comparison is already in progress for these documents"
            ) from None
        await db.refresh(comparison)
        raise exc

    if not await complete_generation(
        db,
        DocumentComparison,
        comparison_id,
        attempt_id,
        status=ComparisonStatus.READY.value,
        values={
            "title": trusted.title,
            "summary": trusted.summary,
            "comparison_dimensions": [
                _dimension_to_dict(dimension) for dimension in trusted.dimensions
            ],
            "key_differences": [_difference_to_dict(item) for item in trusted.key_differences],
            "commonalities": [_commonality_to_dict(item) for item in trusted.commonalities],
            "error_message": None,
        },
    ):
        reloaded = await _comparison_by_signature(db, space_id, signature)
        if reloaded is not None and reloaded.status == ComparisonStatus.READY.value:
            return reloaded, False
        raise ComparisonConflictError("A comparison is already in progress for these documents")

    reloaded = await _comparison_by_signature(db, space_id, signature)
    if reloaded is None:
        raise ComparisonStateError("Comparison could not be reloaded")
    return reloaded, created


async def list_comparisons(
    db: AsyncSession,
    space_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[DocumentComparison] | None:
    if await get_owned_space(db, space_id, user_id) is None:
        return None
    result = await db.execute(
        select(DocumentComparison)
        .options(_MEMBER_LOAD)
        .where(DocumentComparison.knowledge_space_id == space_id)
        .order_by(DocumentComparison.created_at.desc())
    )
    return list(result.scalars().all())


async def get_comparison(
    db: AsyncSession,
    space_id: uuid.UUID,
    comparison_id: uuid.UUID,
    user_id: uuid.UUID,
) -> DocumentComparison | None:
    result = await db.execute(
        select(DocumentComparison)
        .join(KnowledgeSpace, DocumentComparison.knowledge_space_id == KnowledgeSpace.id)
        .options(_MEMBER_LOAD)
        .where(
            DocumentComparison.id == comparison_id,
            DocumentComparison.knowledge_space_id == space_id,
            KnowledgeSpace.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_comparisons_for_document(
    db: AsyncSession,
    document_id: uuid.UUID,
) -> None:
    """Remove every comparison that depends on a document about to be deleted.

    Runs inside the document-deletion transaction so no comparison can survive
    with broken provenance. The member link FKs cascade either way; this removes
    the parent comparison rows explicitly.
    """
    result = await db.execute(
        select(DocumentComparison.id)
        .join(
            DocumentComparisonDocument,
            DocumentComparisonDocument.comparison_id == DocumentComparison.id,
        )
        .where(DocumentComparisonDocument.document_id == document_id)
    )
    comparison_ids = list(result.scalars())
    if comparison_ids:
        await db.execute(
            delete(DocumentComparison).where(DocumentComparison.id.in_(comparison_ids))
        )
