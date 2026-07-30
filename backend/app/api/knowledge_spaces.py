import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.infrastructure.database import get_db
from app.infrastructure.models import KnowledgeSpace, User
from app.schemas.knowledge_space import (
    CreateSpaceRequest,
    SpaceResponse,
    UpdateSpaceRequest,
)

router = APIRouter(prefix="/knowledge-spaces", tags=["knowledge-spaces"])


async def _get_owned_space(
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> KnowledgeSpace:
    result = await db.execute(
        select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.user_id == user_id,
        )
    )
    space = result.scalar_one_or_none()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return space


@router.post("", response_model=SpaceResponse, status_code=201)
async def create_space(
    body: CreateSpaceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    space = KnowledgeSpace(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
    )
    db.add(space)
    await db.commit()
    await db.refresh(space)
    return space


@router.get("", response_model=list[SpaceResponse])
async def list_spaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeSpace)
        .where(KnowledgeSpace.user_id == current_user.id)
        .order_by(KnowledgeSpace.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{space_id}", response_model=SpaceResponse)
async def get_space(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_owned_space(space_id, current_user.id, db)


@router.patch("/{space_id}", response_model=SpaceResponse)
async def update_space(
    space_id: uuid.UUID,
    body: UpdateSpaceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    space = await _get_owned_space(space_id, current_user.id, db)

    if body.name is not None:
        space.name = body.name
    if "description" in body.model_fields_set:
        space.description = body.description

    await db.commit()
    await db.refresh(space)
    return space


@router.delete("/{space_id}", status_code=204)
async def delete_space(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    space = await _get_owned_space(space_id, current_user.id, db)
    await db.delete(space)
    await db.commit()
