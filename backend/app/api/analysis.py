import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.analysis import analyze_document, get_document_analysis
from app.application.dependencies import get_analysis_provider
from app.auth import get_current_user
from app.domain.analysis import DocumentAnalysisProvider
from app.domain.errors import (
    AnalysisConflictError,
    AnalysisContextTooLargeError,
    AnalysisNotFoundError,
    AnalysisStateError,
    AnalysisValidationError,
    ProviderError,
)
from app.infrastructure.database import get_db
from app.infrastructure.models import User
from app.schemas.document_analysis import DocumentAnalysisResponse

router = APIRouter(
    prefix="/knowledge-spaces/{space_id}/documents/{document_id}",
    tags=["document-analysis"],
)


@router.post("/analysis", response_model=DocumentAnalysisResponse, status_code=201)
async def create_document_analysis(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: DocumentAnalysisProvider = Depends(get_analysis_provider),
):
    try:
        analysis, created = await analyze_document(
            db,
            space_id,
            document_id,
            current_user.id,
            provider,
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return analysis
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AnalysisConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (AnalysisStateError, AnalysisContextTooLargeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (AnalysisValidationError, ProviderError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/analysis", response_model=DocumentAnalysisResponse)
async def read_document_analysis(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analysis = await get_document_analysis(db, space_id, document_id, current_user.id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return analysis
