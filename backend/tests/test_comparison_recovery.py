import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.comparisons import (
    comparison_signature,
    create_comparison,
)
from app.application.dependencies import get_comparison_provider
from app.application.generation_lease import claim_generation, complete_generation
from app.config import settings
from app.domain.comparison import (
    DocumentComparisonContext,
    ProviderComparisonResult,
)
from app.domain.errors import ComparisonConflictError, ProviderError
from app.infrastructure.models import DocumentComparison, User
from app.main import app
from tests.test_document_comparison import (
    create_space,
    default_provider_result,
    register_user,
    upload_pdf,
)

SPACES_URL = "/knowledge-spaces"


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def comparisons_path(space_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/comparisons"


def stale_time() -> datetime:
    """A processing_started_at older than the stale timeout (no real sleeps)."""
    return datetime.now(UTC) - timedelta(seconds=settings.generation_stale_after_seconds * 2)


class StubComparisonProvider:
    model_name = "recovery-comparison"

    def __init__(self, result=None, exception=None, gate=False):
        self.calls = 0
        self.context = None
        self.result = result
        self.exception = exception
        self.gate = gate
        self.claimed = asyncio.Event()
        self.release = asyncio.Event()

    async def compare(self, context: DocumentComparisonContext) -> ProviderComparisonResult:
        self.calls += 1
        self.context = context
        if self.gate:
            self.claimed.set()
            await self.release.wait()
        if self.exception is not None:
            raise self.exception
        return self.result if self.result is not None else default_provider_result(context)


def install_provider(stub: StubComparisonProvider) -> None:
    app.dependency_overrides[get_comparison_provider] = lambda: stub


async def user_by_email(db: AsyncSession, email: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


async def seed_comparison(
    db: AsyncSession,
    space_id: uuid.UUID,
    signature: str,
    *,
    started_at: datetime | None,
    attempt_id: uuid.UUID | None,
    status: str = "processing",
    focus: str | None = None,
) -> DocumentComparison:
    row = DocumentComparison(
        knowledge_space_id=space_id,
        status=status,
        comparison_signature=signature,
        focus=focus,
        provider="mock",
        processing_started_at=started_at,
        processing_attempt_id=attempt_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def current_comparison(
    db: AsyncSession, space_id: uuid.UUID, signature: str
) -> DocumentComparison:
    row = await db.scalar(
        select(DocumentComparison).where(
            DocumentComparison.knowledge_space_id == space_id,
            DocumentComparison.comparison_signature == signature,
        )
    )
    assert row is not None
    return row


async def setup_two_documents(
    async_client: AsyncClient,
    email: str,
) -> tuple[str, dict, dict, str]:
    token = await register_user(async_client, email)
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    return token, document_a, document_b, space["id"]


@pytest.mark.asyncio
async def test_comparison_fresh_processing_returns_conflict(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-fresh@test.com"
    )
    signature = comparison_signature(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], None
    )
    old_attempt = uuid.uuid4()
    await seed_comparison(
        db_session,
        uuid.UUID(space_id),
        signature,
        started_at=datetime.now(UTC),
        attempt_id=old_attempt,
    )
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space_id),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 409
    assert stub.calls == 0
    row = await current_comparison(db_session, uuid.UUID(space_id), signature)
    assert row.status == "processing"
    assert row.processing_attempt_id == old_attempt


@pytest.mark.asyncio
async def test_comparison_stale_processing_is_reclaimed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-stale@test.com"
    )
    signature = comparison_signature(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], None
    )
    old_attempt = uuid.uuid4()
    await seed_comparison(
        db_session,
        uuid.UUID(space_id),
        signature,
        started_at=stale_time(),
        attempt_id=old_attempt,
    )
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space_id),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert stub.calls == 1
    row = await current_comparison(db_session, uuid.UUID(space_id), signature)
    assert row.status == "ready"
    assert row.processing_started_at is None
    assert row.processing_attempt_id is None


@pytest.mark.asyncio
async def test_comparison_null_lease_is_treated_as_stale(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-null@test.com"
    )
    signature = comparison_signature(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], None
    )
    await seed_comparison(
        db_session,
        uuid.UUID(space_id),
        signature,
        started_at=None,
        attempt_id=uuid.uuid4(),
    )
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space_id),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_comparison_ready_remains_idempotent(async_client: AsyncClient):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-idem@test.com"
    )
    stub = StubComparisonProvider()
    install_provider(stub)

    first = await async_client.post(
        comparisons_path(space_id),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert first.status_code == 201
    second = await async_client.post(
        comparisons_path(space_id),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_comparison_failed_retry_uses_claim(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-retry@test.com"
    )
    signature = comparison_signature(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], None
    )
    await seed_comparison(
        db_session,
        uuid.UUID(space_id),
        signature,
        started_at=None,
        attempt_id=None,
        status="failed",
    )
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space_id),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert stub.calls == 1
    row = await current_comparison(db_session, uuid.UUID(space_id), signature)
    assert row.status == "ready"
    assert row.error_message is None


@pytest.mark.asyncio
async def test_comparison_provider_failure_marks_active_attempt_failed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-fail@test.com"
    )
    stub = StubComparisonProvider(exception=ProviderError("temporary outage"))
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space_id),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert stub.calls == 1
    rows = (
        await db_session.scalars(
            select(DocumentComparison).where(
                DocumentComparison.knowledge_space_id == uuid.UUID(space_id)
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error_message == "temporary outage"
    assert rows[0].processing_started_at is None
    assert rows[0].processing_attempt_id is None


@pytest.mark.asyncio
async def test_comparison_concurrent_stale_reclaim_single_winner(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-race@test.com"
    )
    user = await user_by_email(db_session, "cmp-rec-race@test.com")
    signature = comparison_signature(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], None
    )
    await seed_comparison(
        db_session,
        uuid.UUID(space_id),
        signature,
        started_at=stale_time(),
        attempt_id=uuid.uuid4(),
    )
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    provider = StubComparisonProvider()

    async with factory() as db_a, factory() as db_b:
        results = await asyncio.gather(
            create_comparison(
                db_a,
                uuid.UUID(space_id),
                [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])],
                None,
                user.id,
                provider,
            ),
            create_comparison(
                db_b,
                uuid.UUID(space_id),
                [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])],
                None,
                user.id,
                provider,
            ),
            return_exceptions=True,
        )

    outcomes = []
    for result in results:
        if isinstance(result, Exception):
            assert isinstance(result, ComparisonConflictError)
            outcomes.append("conflict")
        else:
            outcomes.append("ready")
    assert provider.calls == 1
    assert "ready" in outcomes
    assert all(name in {"ready", "conflict"} for name in outcomes)
    row = await current_comparison(db_session, uuid.UUID(space_id), signature)
    assert row.status == "ready"
    assert row.title == "Fixture Comparison"


@pytest.mark.asyncio
async def test_comparison_concurrent_new_creation_single_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-new-race@test.com"
    )
    user = await user_by_email(db_session, "cmp-rec-new-race@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    provider = StubComparisonProvider()

    async with factory() as db_a, factory() as db_b:
        results = await asyncio.gather(
            create_comparison(
                db_a,
                uuid.UUID(space_id),
                [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])],
                None,
                user.id,
                provider,
            ),
            create_comparison(
                db_b,
                uuid.UUID(space_id),
                [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])],
                None,
                user.id,
                provider,
            ),
            return_exceptions=True,
        )

    outcomes = []
    for result in results:
        if isinstance(result, Exception):
            assert isinstance(result, ComparisonConflictError)
            outcomes.append("conflict")
        else:
            outcomes.append("ready")
    assert provider.calls == 1
    assert "ready" in outcomes
    rows = (
        await db_session.scalars(
            select(DocumentComparison).where(
                DocumentComparison.knowledge_space_id == uuid.UUID(space_id)
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].status == "ready"


@pytest.mark.asyncio
async def test_comparison_concurrent_canonical_order_single_identity(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    """[A, B] and [B, A] racing concurrently must resolve to one identity."""
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-order-race@test.com"
    )
    user = await user_by_email(db_session, "cmp-rec-order-race@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    provider = StubComparisonProvider()

    async with factory() as db_a, factory() as db_b:
        results = await asyncio.gather(
            create_comparison(
                db_a,
                uuid.UUID(space_id),
                [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])],
                None,
                user.id,
                provider,
            ),
            create_comparison(
                db_b,
                uuid.UUID(space_id),
                [uuid.UUID(document_b["id"]), uuid.UUID(document_a["id"])],
                None,
                user.id,
                provider,
            ),
            return_exceptions=True,
        )

    outcomes = []
    for result in results:
        if isinstance(result, Exception):
            assert isinstance(result, ComparisonConflictError)
            outcomes.append("conflict")
        else:
            outcomes.append("ready")
    assert provider.calls == 1
    assert "ready" in outcomes
    rows = (
        await db_session.scalars(
            select(DocumentComparison).where(
                DocumentComparison.knowledge_space_id == uuid.UUID(space_id)
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].status == "ready"
    from app.infrastructure.models import DocumentComparisonDocument

    member_count = await db_session.scalar(
        select(func.count())
        .select_from(DocumentComparisonDocument)
        .where(DocumentComparisonDocument.comparison_id == rows[0].id)
    )
    assert member_count == 2


@pytest.mark.asyncio
async def test_comparison_old_claim_cannot_overwrite_newer_ready(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-sup@test.com"
    )
    user = await user_by_email(db_session, "cmp-rec-sup@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    document_ids = [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])]
    signature = comparison_signature(document_ids, None)

    old_provider = StubComparisonProvider(gate=True)
    winner_provider = StubComparisonProvider()

    async with factory() as db_a:
        task_a = asyncio.create_task(
            create_comparison(
                db_a,
                uuid.UUID(space_id),
                document_ids,
                None,
                user.id,
                old_provider,
            )
        )
        try:
            await old_provider.claimed.wait()
            row_id = await db_session.scalar(
                select(DocumentComparison.id).where(
                    DocumentComparison.knowledge_space_id == uuid.UUID(space_id),
                    DocumentComparison.comparison_signature == signature,
                )
            )
            await db_session.execute(
                update(DocumentComparison)
                .where(DocumentComparison.id == row_id)
                .values(processing_started_at=stale_time())
            )
            await db_session.commit()

            async with factory() as db_b:
                winner_result, _ = await create_comparison(
                    db_b,
                    uuid.UUID(space_id),
                    document_ids,
                    None,
                    user.id,
                    winner_provider,
                )
            assert winner_result.status == "ready"

            old_provider.release.set()
            result_a, _ = await task_a
            assert result_a.status == "ready"

            row = await current_comparison(db_session, uuid.UUID(space_id), signature)
            assert row.status == "ready"
            assert row.title == "Fixture Comparison"
            assert row.processing_started_at is None
            assert row.processing_attempt_id is None
            assert winner_provider.calls == 1
        finally:
            old_provider.release.set()


@pytest.mark.asyncio
async def test_comparison_old_claim_cannot_overwrite_newer_failure(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-supfail@test.com"
    )
    user = await user_by_email(db_session, "cmp-rec-supfail@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    document_ids = [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])]
    signature = comparison_signature(document_ids, None)

    old_provider = StubComparisonProvider(exception=ProviderError("late failure"), gate=True)
    winner_provider = StubComparisonProvider()

    async with factory() as db_a:
        task_a = asyncio.create_task(
            create_comparison(
                db_a,
                uuid.UUID(space_id),
                document_ids,
                None,
                user.id,
                old_provider,
            )
        )
        try:
            await old_provider.claimed.wait()
            row_id = await db_session.scalar(
                select(DocumentComparison.id).where(
                    DocumentComparison.knowledge_space_id == uuid.UUID(space_id),
                    DocumentComparison.comparison_signature == signature,
                )
            )
            await db_session.execute(
                update(DocumentComparison)
                .where(DocumentComparison.id == row_id)
                .values(processing_started_at=stale_time())
            )
            await db_session.commit()

            async with factory() as db_b:
                winner_result, _ = await create_comparison(
                    db_b,
                    uuid.UUID(space_id),
                    document_ids,
                    None,
                    user.id,
                    winner_provider,
                )
            assert winner_result.status == "ready"

            old_provider.release.set()
            result_a, _ = await task_a
            assert result_a.status == "ready"

            row = await current_comparison(db_session, uuid.UUID(space_id), signature)
            assert row.status == "ready"
            assert row.error_message is None
            assert row.title == "Fixture Comparison"
            assert winner_provider.calls == 1
        finally:
            old_provider.release.set()


@pytest.mark.asyncio
async def test_claim_and_complete_lease_helpers_support_comparison(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token, document_a, document_b, space_id = await setup_two_documents(
        async_client, "cmp-rec-lease@test.com"
    )
    signature = comparison_signature(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], None
    )
    row = await seed_comparison(
        db_session,
        uuid.UUID(space_id),
        signature,
        started_at=stale_time(),
        attempt_id=uuid.uuid4(),
    )

    claim = await claim_generation(
        db_session,
        DocumentComparison,
        row.id,
        provider="mock",
        model_name="lease-model",
    )
    assert claim is not None
    attempt_id, _ = claim
    row_id = row.id

    rejected = await complete_generation(
        db_session,
        DocumentComparison,
        row_id,
        uuid.uuid4(),
        status="ready",
        values={"error_message": None},
    )
    assert rejected is False
    after = await current_comparison(db_session, uuid.UUID(space_id), signature)
    assert after.status == "processing"
    assert after.processing_attempt_id == attempt_id

    accepted = await complete_generation(
        db_session,
        DocumentComparison,
        row_id,
        attempt_id,
        status="ready",
        values={"title": "Leased Title", "error_message": None},
    )
    assert accepted is True
    after = await current_comparison(db_session, uuid.UUID(space_id), signature)
    await db_session.refresh(after)
    assert after.status == "ready"
    assert after.title == "Leased Title"
    assert after.processing_started_at is None
    assert after.processing_attempt_id is None
