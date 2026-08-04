import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.actions import (
    generate_actions,
    get_document_action_set,
    update_action_status,
)
from app.application.dependencies import get_action_provider
from app.auth import get_current_user
from app.domain.actions import ActionStatus, DocumentActionProvider
from app.domain.errors import (
    ActionConflictError,
    ActionContextTooLargeError,
    ActionNotFoundError,
    ActionStateError,
    ActionValidationError,
    ProviderError,
)
from app.infrastructure.database import get_db
from app.infrastructure.models import User
from app.schemas.actions import ActionItemResponse, ActionStatusUpdate, DocumentActionsResponse

router = APIRouter(
    prefix="/knowledge-spaces/{space_id}/documents/{document_id}",
    tags=["document-actions"],
)


@router.post("/actions", response_model=DocumentActionsResponse, status_code=201)
async def create_document_actions(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider: DocumentActionProvider = Depends(get_action_provider),
):
    try:
        action_set, created = await generate_actions(
            db, space_id, document_id, current_user.id, provider
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return action_set
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ActionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (ActionStateError, ActionContextTooLargeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (ActionValidationError, ProviderError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/actions", response_model=DocumentActionsResponse)
async def read_document_actions(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    action_set = await get_document_action_set(db, space_id, document_id, current_user.id)
    if action_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return action_set


@router.patch("/actions/{action_id}", response_model=ActionItemResponse)
async def update_document_action(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    action_id: uuid.UUID,
    body: ActionStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await update_action_status(
            db,
            space_id,
            document_id,
            action_id,
            current_user.id,
            ActionStatus(body.status),
        )
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
