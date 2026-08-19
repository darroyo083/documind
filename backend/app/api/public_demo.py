import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import settings
from app.demo_fixtures import (
    COMPARISON_ID,
    MEMBERSHIP_DOCUMENT_ID,
    RENEWAL_DOCUMENT_ID,
    demo_actions,
    demo_analysis,
    demo_answer,
    demo_comparison,
    demo_documents,
    demo_intelligence,
    demo_search,
    demo_space,
)
from app.schemas.actions import DocumentActionsResponse
from app.schemas.comparisons import ComparisonSummaryResponse, DocumentComparisonResponse
from app.schemas.document import AnswerResponse, AskRequest, DocumentResponse
from app.schemas.document_analysis import DocumentAnalysisResponse
from app.schemas.intelligence import SpaceIntelligenceResponse
from app.schemas.knowledge_space import SpaceResponse
from app.schemas.search import GlobalSearchHitResponse

router = APIRouter(prefix="/public-demo", tags=["public-demo"])


def require_public_demo_mode() -> None:
    if not settings.public_demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _require_document(document_id: uuid.UUID) -> None:
    if document_id not in {MEMBERSHIP_DOCUMENT_ID, RENEWAL_DOCUMENT_ID}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get(
    "/space", response_model=SpaceResponse, dependencies=[Depends(require_public_demo_mode)]
)
async def read_demo_space():
    return demo_space()


@router.get(
    "/space/documents",
    response_model=list[DocumentResponse],
    dependencies=[Depends(require_public_demo_mode)],
)
async def read_demo_documents():
    return demo_documents()


@router.get(
    "/space/documents/{document_id}/analysis",
    response_model=DocumentAnalysisResponse,
    dependencies=[Depends(require_public_demo_mode)],
)
async def read_demo_analysis(document_id: uuid.UUID):
    _require_document(document_id)
    return demo_analysis(document_id)


@router.get(
    "/space/documents/{document_id}/actions",
    response_model=DocumentActionsResponse,
    dependencies=[Depends(require_public_demo_mode)],
)
async def read_demo_actions(document_id: uuid.UUID):
    _require_document(document_id)
    return demo_actions(document_id)


@router.get(
    "/space/comparisons",
    response_model=list[ComparisonSummaryResponse],
    dependencies=[Depends(require_public_demo_mode)],
)
async def read_demo_comparisons():
    comparison = demo_comparison()
    return [
        {
            "id": comparison["id"],
            "status": comparison["status"],
            "focus": comparison["focus"],
            "title": comparison["title"],
            "documents": comparison["documents"],
            "created_at": comparison["created_at"],
            "updated_at": comparison["updated_at"],
        }
    ]


@router.get(
    "/space/comparisons/{comparison_id}",
    response_model=DocumentComparisonResponse,
    dependencies=[Depends(require_public_demo_mode)],
)
async def read_demo_comparison(comparison_id: uuid.UUID):
    if comparison_id != COMPARISON_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return demo_comparison()


@router.get(
    "/space/intelligence",
    response_model=SpaceIntelligenceResponse,
    dependencies=[Depends(require_public_demo_mode)],
)
async def read_demo_intelligence():
    return demo_intelligence()


@router.post(
    "/space/ask", response_model=AnswerResponse, dependencies=[Depends(require_public_demo_mode)]
)
async def ask_demo(body: AskRequest):
    return demo_answer(body.question)


@router.get(
    "/search",
    response_model=list[GlobalSearchHitResponse],
    dependencies=[Depends(require_public_demo_mode)],
)
async def search_demo(q: str = Query(..., min_length=1, max_length=500)):
    return demo_search(q)
