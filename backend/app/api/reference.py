from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.reference import list_reference_documents
from app.auth import get_current_user
from app.infrastructure.database import get_db
from app.infrastructure.models import User
from app.schemas.reference import ReferenceDocumentResponse

router = APIRouter(prefix="/reference-library", tags=["reference-library"])


@router.get("", response_model=list[ReferenceDocumentResponse])
async def read_reference_library(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List application-managed reference documents (read-only metadata)."""
    return await list_reference_documents(db)
