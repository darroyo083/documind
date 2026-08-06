import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.comparisons import (
    create_comparison,
    get_comparison,
    list_comparisons,
)
from app.application.dependencies import get_comparison_provider
from app.auth import get_current_user
from app.domain.comparison import DocumentComparisonProvider
from app.domain.errors import (
    ComparisonConflictError,
    ComparisonContextTooLargeError,
    ComparisonNotFoundError,
    ComparisonStateError,
    ComparisonValidationError,
    ProviderError,
)
from app.infrastructure.database import get_db
from app.infrastructure.models import DocumentComparison, DocumentComparisonDocument, User
from app.schemas.comparisons import (
    ComparisonSummaryResponse,
    CreateComparisonRequest,
    DocumentComparisonResponse,
)

router = APIRouter(prefix="/knowledge-spaces/{space_id}", tags=["document-comparisons"])


def _member_to_dict(member: DocumentComparisonDocument) -> dict:
    return {
        "document_id": member.document_id,
        "original_filename": member.document.original_filename,
        "position": member.position,
    }


def _serialize_summary(row: DocumentComparison) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "focus": row.focus,
        "title": row.title,
        "documents": [_member_to_dict(member) for member in row.members],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_detail(row: DocumentComparison) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "focus": row.focus,
        "title": row.title,
        "summary": row.summary,
        "documents": [_member_to_dict(member) for member in row.members],
        "dimensions": row.comparison_dimensions,
        "key_differences": row.key_differences,
        "commonalities": row.commonalities,
        "provider": row.provider,
        "model": row.model,
        "error_message": row.error_message,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.post("/comparisons", response_model=DocumentComparisonResponse, status_code=201)
async def create_document_comparison(
    space_id: uuid.UUID,
    body: CreateComparisonRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: DocumentComparisonProvider = Depends(get_comparison_provider),
):
    try:
        comparison, created = await create_comparison(
            db,
            space_id,
            body.document_ids,
            body.focus,
            current_user.id,
            provider,
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return _serialize_detail(comparison)
    except ComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ComparisonConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (ComparisonStateError, ComparisonContextTooLargeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (ComparisonValidationError, ProviderError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/comparisons", response_model=list[ComparisonSummaryResponse])
async def read_comparisons(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    comparisons = await list_comparisons(db, space_id, current_user.id)
    if comparisons is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return [_serialize_summary(comparison) for comparison in comparisons]


@router.get("/comparisons/{comparison_id}", response_model=DocumentComparisonResponse)
async def read_comparison(
    space_id: uuid.UUID,
    comparison_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    comparison = await get_comparison(db, space_id, comparison_id, current_user.id)
    if comparison is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _serialize_detail(comparison)
