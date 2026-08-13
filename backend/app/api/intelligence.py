import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dependencies import get_intelligence_provider
from app.application.intelligence import (
    get_intelligence_state,
    refresh_intelligence,
)
from app.auth import get_current_user
from app.domain.errors import (
    IntelligenceConflictError,
    IntelligenceContextTooLargeError,
    IntelligenceNotFoundError,
    IntelligenceStateError,
    IntelligenceValidationError,
    ProviderError,
)
from app.domain.intelligence import SpaceIntelligenceProvider
from app.infrastructure.database import get_db
from app.infrastructure.models import SpaceIntelligence, User
from app.schemas.intelligence import SpaceIntelligenceResponse

router = APIRouter(prefix="/knowledge-spaces/{space_id}", tags=["space-intelligence"])

_EMPTY_ITEMS = {
    "summary": "",
    "key_facts": [],
    "contradictions": [],
    "dates": [],
    "open_questions": [],
}


def _serialize(
    snapshot: SpaceIntelligence | None, ready_document_count: int, is_stale: bool
) -> dict:
    if snapshot is None:
        return {
            "status": "none",
            "is_stale": False,
            "ready_document_count": ready_document_count,
            **_EMPTY_ITEMS,
            "provider": None,
            "model": None,
            "error_message": None,
            "created_at": None,
            "updated_at": None,
        }
    return {
        "status": snapshot.status,
        "is_stale": is_stale,
        "ready_document_count": ready_document_count,
        "summary": snapshot.summary,
        "key_facts": snapshot.key_facts,
        "contradictions": snapshot.contradictions,
        "dates": snapshot.dates,
        "open_questions": snapshot.open_questions,
        "provider": snapshot.provider,
        "model": snapshot.model,
        "error_message": snapshot.error_message,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }


@router.get("/intelligence", response_model=SpaceIntelligenceResponse)
async def read_intelligence(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    documents, snapshot, _signature, is_stale = await get_intelligence_state(
        db, space_id, current_user.id
    )
    if documents is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _serialize(snapshot, len(documents), is_stale)


@router.post("/intelligence", response_model=SpaceIntelligenceResponse)
async def generate_intelligence(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: SpaceIntelligenceProvider = Depends(get_intelligence_provider),
):
    try:
        snapshot, _created = await refresh_intelligence(db, space_id, current_user.id, provider)
    except IntelligenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IntelligenceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (IntelligenceStateError, IntelligenceContextTooLargeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (IntelligenceValidationError, ProviderError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    documents = await get_intelligence_state(db, space_id, current_user.id)
    ready = documents[0]
    if ready is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _serialize(snapshot, len(ready), False)
