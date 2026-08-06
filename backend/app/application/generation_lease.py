import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.infrastructure.models import DocumentActionSet, DocumentAnalysis

PROCESSING = "processing"
READY = "ready"
FAILED = "failed"


def stale_cutoff(now: datetime | None = None) -> datetime:
    """A ``processing_started_at`` older than this cutoff is a stale claim."""
    reference = now if now is not None else datetime.now(UTC)
    return reference - timedelta(seconds=settings.generation_stale_after_seconds)


async def claim_generation[LeaseRow: (DocumentAnalysis, DocumentActionSet)](
    db: AsyncSession,
    model: type[LeaseRow],
    row_id: uuid.UUID,
    *,
    provider: str,
    model_name: str,
) -> tuple[uuid.UUID, datetime] | None:
    """Atomically claim a generation row for this request.

    Succeeds only when the row is currently claimable:
    - ``failed`` rows may always be retried;
    - ``processing`` rows are reclaimable only when their lease is stale
      (``processing_started_at`` is NULL or older than the stale cutoff).

    The claim is a single compare-and-set UPDATE so exactly one of several
    concurrent reclaimers wins. Returns the new attempt token and lease start
    time, or ``None`` when the row was already claimed by someone else.
    """
    now = datetime.now(UTC)
    cutoff = stale_cutoff(now)
    attempt_id = uuid.uuid4()
    result = await db.execute(
        update(model)
        .where(
            model.id == row_id,
            or_(
                and_(
                    model.status == PROCESSING,
                    or_(
                        model.processing_started_at.is_(None),
                        model.processing_started_at < cutoff,
                    ),
                ),
                model.status == FAILED,
            ),
        )
        .values(
            status=PROCESSING,
            processing_started_at=now,
            processing_attempt_id=attempt_id,
            provider=provider,
            model=model_name,
            error_message=None,
        )
        .returning(model.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        return None
    await db.commit()
    return attempt_id, now


async def complete_generation[LeaseRow: (DocumentAnalysis, DocumentActionSet)](
    db: AsyncSession,
    model: type[LeaseRow],
    row_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    status: str,
    values: dict[str, Any] | None = None,
) -> bool:
    """Persist a terminal state only if this request still owns the claim.

    The compare-and-set UPDATE only matches rows still in ``processing`` with
    this request's attempt token, so a superseded (lost-lease) request can
    never overwrite a newer claim. Commits on success and rolls back on
    failure; pending ORM changes (e.g. replaced action rows) are included in
    the same transaction and discarded when the claim was lost.
    """
    result = await db.execute(
        update(model)
        .where(
            model.id == row_id,
            model.status == PROCESSING,
            model.processing_attempt_id == attempt_id,
        )
        .values(
            status=status,
            processing_started_at=None,
            processing_attempt_id=None,
            **(values or {}),
        )
        .returning(model.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        return False
    await db.commit()
    return True
