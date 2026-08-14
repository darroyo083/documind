import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dependencies import get_embedding_provider
from app.application.search import search_spaces
from app.auth import get_current_user
from app.domain.errors import ProviderError
from app.domain.rag import EmbeddingProvider
from app.infrastructure.database import get_db
from app.infrastructure.models import User
from app.schemas.search import GlobalSearchHitResponse

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[GlobalSearchHitResponse])
async def global_search(
    q: str = Query(..., min_length=1),
    space_ids: list[uuid.UUID] | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
):
    try:
        return await search_spaces(
            db, current_user.id, q, embedding_provider, space_ids, limit
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
