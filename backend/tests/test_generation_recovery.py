import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.application.actions import generate_actions
from app.application.analysis import analyze_document
from app.application.dependencies import get_action_provider, get_analysis_provider
from app.application.generation_lease import claim_generation, complete_generation
from app.config import settings
from app.domain.actions import DocumentActionContext, ProviderAction, ProviderDocumentActions
from app.domain.analysis import (
    DocumentAnalysisContext,
    ProviderDocumentAnalysis,
    ProviderImportantDate,
    ProviderKeyFact,
)
from app.domain.errors import ActionConflictError, AnalysisConflictError, ProviderError
from app.infrastructure.models import (
    DocumentActionSet,
    DocumentAnalysis,
    User,
)
from app.main import app
from tests.pdf_factory import text_pdf

SPACES_URL = "/knowledge-spaces"


async def register_user(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "TestPass1",
            "display_name": email.split("@")[0],
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_space(client: AsyncClient, token: str, name: str = "Recovery") -> dict:
    response = await client.post(SPACES_URL, json={"name": name}, headers=auth_header(token))
    assert response.status_code == 201
    return response.json()


async def upload_pdf(client: AsyncClient, token: str, space_id: str, pages: list[str]):
    bytes_data = text_pdf(pages[0])
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": ("evidence.pdf", bytes_data, "application/pdf")},
    )


def analysis_path(space_id: str, document_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/documents/{document_id}/analysis"


def actions_path(space_id: str, document_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/documents/{document_id}/actions"


def stale_time() -> datetime:
    """A processing_started_at older than the stale timeout (no real sleeps)."""
    return datetime.now(UTC) - timedelta(seconds=settings.generation_stale_after_seconds * 2)


def default_analysis_result(context: DocumentAnalysisContext) -> ProviderDocumentAnalysis:
    source_id = context.sources[0].source_id
    return ProviderDocumentAnalysis(
        document_type="contract",
        normalized_title="Fixture Contract",
        summary="A fixture contract with explicit, verifiable evidence.",
        important_dates=[
            ProviderImportantDate(
                label="Effective date",
                value="1 September 2026",
                normalized_date="2026-09-01",
                source_ids=[source_id],
            )
        ],
        key_facts=[
            ProviderKeyFact(
                label="Termination notice",
                value="30 days",
                source_ids=[source_id],
            )
        ],
    )


def default_actions_result(context: DocumentActionContext) -> ProviderDocumentActions:
    source_id = context.sources[0].source_id
    return ProviderDocumentActions(
        actions=[
            ProviderAction(
                action_type="deadline",
                title="Pay the invoice",
                description=None,
                timing_text="31 January 2027",
                due_date="2027-01-31",
                source_ids=[source_id],
            )
        ]
    )


class StubAnalysisProvider:
    model_name = "recovery-analysis"

    def __init__(self, result=None, exception=None, gate=False):
        self.calls = 0
        self.context = None
        self.result = result
        self.exception = exception
        self.gate = gate
        self.claimed = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(self, context: DocumentAnalysisContext) -> ProviderDocumentAnalysis:
        self.calls += 1
        self.context = context
        if self.gate:
            self.claimed.set()
            await self.release.wait()
        if self.exception is not None:
            raise self.exception
        return self.result if self.result is not None else default_analysis_result(context)


class StubActionProvider:
    model_name = "recovery-actions"

    def __init__(self, result=None, exception=None, gate=False):
        self.calls = 0
        self.context = None
        self.result = result
        self.exception = exception
        self.gate = gate
        self.claimed = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_actions(self, context: DocumentActionContext) -> ProviderDocumentActions:
        self.calls += 1
        self.context = context
        if self.gate:
            self.claimed.set()
            await self.release.wait()
        if self.exception is not None:
            raise self.exception
        return self.result if self.result is not None else default_actions_result(context)


def install_analysis_provider(stub: StubAnalysisProvider) -> None:
    app.dependency_overrides[get_analysis_provider] = lambda: stub


def install_action_provider(stub: StubActionProvider) -> None:
    app.dependency_overrides[get_action_provider] = lambda: stub


async def user_by_email(db: AsyncSession, email: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


async def seed_analysis(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    started_at: datetime | None,
    attempt_id: uuid.UUID | None,
    status: str = "processing",
) -> DocumentAnalysis:
    row = DocumentAnalysis(
        document_id=document_id,
        status=status,
        provider="mock",
        processing_started_at=started_at,
        processing_attempt_id=attempt_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def seed_action_set(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    started_at: datetime | None,
    attempt_id: uuid.UUID | None,
    status: str = "processing",
) -> DocumentActionSet:
    row = DocumentActionSet(
        document_id=document_id,
        status=status,
        provider="mock",
        processing_started_at=started_at,
        processing_attempt_id=attempt_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def current_analysis(db: AsyncSession, document_id: uuid.UUID) -> DocumentAnalysis:
    row = await db.scalar(
        select(DocumentAnalysis).where(DocumentAnalysis.document_id == document_id)
    )
    assert row is not None
    return row


async def current_action_set(db: AsyncSession, document_id: uuid.UUID) -> DocumentActionSet:
    row = await db.scalar(
        select(DocumentActionSet)
        .options(selectinload(DocumentActionSet.actions))
        .where(DocumentActionSet.document_id == document_id)
    )
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_analysis_fresh_processing_returns_conflict(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "recovery-fresh-a@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubAnalysisProvider()
    install_analysis_provider(stub)
    old_attempt = uuid.uuid4()
    await seed_analysis(
        db_session,
        uuid.UUID(document["id"]),
        started_at=datetime.now(UTC),
        attempt_id=old_attempt,
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 409
    assert stub.calls == 0
    row = await current_analysis(db_session, uuid.UUID(document["id"]))
    assert row.status == "processing"
    assert row.processing_attempt_id == old_attempt


@pytest.mark.asyncio
async def test_actions_fresh_processing_returns_conflict(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "recovery-fresh-b@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubActionProvider()
    install_action_provider(stub)
    old_attempt = uuid.uuid4()
    await seed_action_set(
        db_session,
        uuid.UUID(document["id"]),
        started_at=datetime.now(UTC),
        attempt_id=old_attempt,
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 409
    assert stub.calls == 0
    row = await current_action_set(db_session, uuid.UUID(document["id"]))
    assert row.status == "processing"
    assert row.processing_attempt_id == old_attempt


@pytest.mark.asyncio
async def test_analysis_stale_processing_is_reclaimed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "recovery-stale-a@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubAnalysisProvider()
    install_analysis_provider(stub)
    old_attempt = uuid.uuid4()
    await seed_analysis(
        db_session,
        uuid.UUID(document["id"]),
        started_at=stale_time(),
        attempt_id=old_attempt,
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert stub.calls == 1
    row = await current_analysis(db_session, uuid.UUID(document["id"]))
    assert row.status == "ready"
    assert row.processing_started_at is None
    assert row.processing_attempt_id is None


@pytest.mark.asyncio
async def test_actions_stale_processing_is_reclaimed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "recovery-stale-b@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubActionProvider()
    install_action_provider(stub)
    await seed_action_set(
        db_session,
        uuid.UUID(document["id"]),
        started_at=stale_time(),
        attempt_id=uuid.uuid4(),
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert len(response.json()["actions"]) == 1
    assert stub.calls == 1
    row = await current_action_set(db_session, uuid.UUID(document["id"]))
    assert row.status == "ready"
    assert row.processing_started_at is None
    assert row.processing_attempt_id is None


@pytest.mark.asyncio
async def test_analysis_null_lease_is_treated_as_stale(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "recovery-null-lease@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubAnalysisProvider()
    install_analysis_provider(stub)
    await seed_analysis(
        db_session,
        uuid.UUID(document["id"]),
        started_at=None,
        attempt_id=uuid.uuid4(),
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_analysis_concurrent_stale_reclaim_single_winner(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token = await register_user(async_client, "recovery-race-a@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    user = await user_by_email(db_session, "recovery-race-a@test.com")
    await seed_analysis(
        db_session,
        uuid.UUID(document["id"]),
        started_at=stale_time(),
        attempt_id=uuid.uuid4(),
    )
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    provider = StubAnalysisProvider()

    async with factory() as db_a, factory() as db_b:
        results = await asyncio.gather(
            analyze_document(
                db_a,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                provider,
            ),
            analyze_document(
                db_b,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                provider,
            ),
            return_exceptions=True,
        )

    outcomes = []
    for result in results:
        if isinstance(result, Exception):
            assert isinstance(result, AnalysisConflictError)
            outcomes.append("conflict")
        else:
            outcomes.append("ready")
    assert provider.calls == 1
    assert "ready" in outcomes
    assert all(name in {"ready", "conflict"} for name in outcomes)
    row = await current_analysis(db_session, uuid.UUID(document["id"]))
    assert row.status == "ready"
    assert row.normalized_title == "Fixture Contract"


@pytest.mark.asyncio
async def test_actions_concurrent_stale_reclaim_single_winner(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token = await register_user(async_client, "recovery-race-b@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    user = await user_by_email(db_session, "recovery-race-b@test.com")
    await seed_action_set(
        db_session,
        uuid.UUID(document["id"]),
        started_at=stale_time(),
        attempt_id=uuid.uuid4(),
    )
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    provider = StubActionProvider()

    async with factory() as db_a, factory() as db_b:
        results = await asyncio.gather(
            generate_actions(
                db_a,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                provider,
            ),
            generate_actions(
                db_b,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                provider,
            ),
            return_exceptions=True,
        )

    outcomes = []
    for result in results:
        if isinstance(result, Exception):
            assert isinstance(result, ActionConflictError)
            outcomes.append("conflict")
        else:
            outcomes.append("ready")
    assert provider.calls == 1
    assert "ready" in outcomes
    assert all(name in {"ready", "conflict"} for name in outcomes)
    row = await current_action_set(db_session, uuid.UUID(document["id"]))
    assert row.status == "ready"


@pytest.mark.asyncio
async def test_analysis_old_claim_cannot_overwrite_newer_ready(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token = await register_user(async_client, "recovery-sup-a@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    user = await user_by_email(db_session, "recovery-sup-a@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    old_provider = StubAnalysisProvider(
        result=ProviderDocumentAnalysis(
            document_type="contract",
            normalized_title="OLD SUPERSEDED ATTEMPT",
            summary="This write must be discarded.",
            important_dates=[],
            key_facts=[],
        ),
        gate=True,
    )
    winner_provider = StubAnalysisProvider()

    async with factory() as db_a:
        task_a = asyncio.create_task(
            analyze_document(
                db_a,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                old_provider,
            )
        )
        try:
            await old_provider.claimed.wait()
            document_uuid = uuid.UUID(document["id"])
            row_id = await db_session.scalar(
                select(DocumentAnalysis.id).where(DocumentAnalysis.document_id == document_uuid)
            )
            await db_session.execute(
                update(DocumentAnalysis)
                .where(DocumentAnalysis.id == row_id)
                .values(processing_started_at=stale_time())
            )
            await db_session.commit()

            async with factory() as db_b:
                winner_result, _ = await analyze_document(
                    db_b,
                    uuid.UUID(space["id"]),
                    document_uuid,
                    user.id,
                    winner_provider,
                )
            assert winner_result.status == "ready"

            old_provider.release.set()
            result_a, created_a = await task_a
            assert created_a is False
            assert result_a.status == "ready"

            row = await current_analysis(db_session, document_uuid)
            assert row.status == "ready"
            assert row.normalized_title == "Fixture Contract"
            assert row.processing_started_at is None
            assert row.processing_attempt_id is None
            assert winner_provider.calls == 1
        finally:
            old_provider.release.set()


@pytest.mark.asyncio
async def test_actions_old_claim_cannot_overwrite_newer_ready(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token = await register_user(async_client, "recovery-sup-b@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    user = await user_by_email(db_session, "recovery-sup-b@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    old_provider = StubActionProvider(
        result=ProviderDocumentActions(
            actions=[
                ProviderAction(
                    action_type="required_action",
                    title="OLD SUPERSEDED ACTION",
                    description=None,
                    timing_text=None,
                    due_date=None,
                    source_ids=[f"chunk:{uuid.uuid4()}"],
                )
            ]
        ),
        gate=True,
    )
    winner_provider = StubActionProvider()

    async with factory() as db_a:
        task_a = asyncio.create_task(
            generate_actions(
                db_a,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                old_provider,
            )
        )
        try:
            await old_provider.claimed.wait()
            document_uuid = uuid.UUID(document["id"])
            row_id = await db_session.scalar(
                select(DocumentActionSet.id).where(DocumentActionSet.document_id == document_uuid)
            )
            await db_session.execute(
                update(DocumentActionSet)
                .where(DocumentActionSet.id == row_id)
                .values(processing_started_at=stale_time())
            )
            await db_session.commit()

            async with factory() as db_b:
                winner_result, _ = await generate_actions(
                    db_b,
                    uuid.UUID(space["id"]),
                    document_uuid,
                    user.id,
                    winner_provider,
                )
            assert winner_result.status == "ready"

            old_provider.release.set()
            result_a, created_a = await task_a
            assert created_a is False
            assert result_a.status == "ready"

            row = await current_action_set(db_session, document_uuid)
            assert row.status == "ready"
            assert len(row.actions) == 1
            assert row.actions[0].title == "Pay the invoice"
            assert row.processing_started_at is None
            assert row.processing_attempt_id is None
            assert winner_provider.calls == 1
        finally:
            old_provider.release.set()


@pytest.mark.asyncio
async def test_analysis_provider_failure_marks_active_attempt_failed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "recovery-fail-a@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubAnalysisProvider(exception=ProviderError("temporary outage"))
    install_analysis_provider(stub)
    await seed_analysis(
        db_session,
        uuid.UUID(document["id"]),
        started_at=stale_time(),
        attempt_id=uuid.uuid4(),
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert stub.calls == 1
    row = await current_analysis(db_session, uuid.UUID(document["id"]))
    assert row.status == "failed"
    assert row.error_message == "temporary outage"
    assert row.processing_started_at is None
    assert row.processing_attempt_id is None


@pytest.mark.asyncio
async def test_actions_provider_failure_marks_active_attempt_failed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "recovery-fail-b@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubActionProvider(exception=ProviderError("temporary outage"))
    install_action_provider(stub)
    await seed_action_set(
        db_session,
        uuid.UUID(document["id"]),
        started_at=stale_time(),
        attempt_id=uuid.uuid4(),
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert stub.calls == 1
    row = await current_action_set(db_session, uuid.UUID(document["id"]))
    assert row.status == "failed"
    assert row.error_message == "temporary outage"
    assert row.processing_started_at is None
    assert row.processing_attempt_id is None


@pytest.mark.asyncio
async def test_analysis_superseded_failure_cannot_fail_newer_claim(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token = await register_user(async_client, "recovery-supfail-a@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    user = await user_by_email(db_session, "recovery-supfail-a@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    old_provider = StubAnalysisProvider(
        exception=ProviderError("late failure"),
        gate=True,
    )
    winner_provider = StubAnalysisProvider()

    async with factory() as db_a:
        task_a = asyncio.create_task(
            analyze_document(
                db_a,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                old_provider,
            )
        )
        try:
            await old_provider.claimed.wait()
            document_uuid = uuid.UUID(document["id"])
            row_id = await db_session.scalar(
                select(DocumentAnalysis.id).where(DocumentAnalysis.document_id == document_uuid)
            )
            await db_session.execute(
                update(DocumentAnalysis)
                .where(DocumentAnalysis.id == row_id)
                .values(processing_started_at=stale_time())
            )
            await db_session.commit()

            async with factory() as db_b:
                winner_result, _ = await analyze_document(
                    db_b,
                    uuid.UUID(space["id"]),
                    document_uuid,
                    user.id,
                    winner_provider,
                )
            assert winner_result.status == "ready"

            old_provider.release.set()
            result_a, created_a = await task_a
            assert created_a is False
            assert result_a.status == "ready"

            row = await current_analysis(db_session, document_uuid)
            assert row.status == "ready"
            assert row.error_message is None
            assert row.normalized_title == "Fixture Contract"
        finally:
            old_provider.release.set()


@pytest.mark.asyncio
async def test_actions_superseded_failure_cannot_fail_newer_claim(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token = await register_user(async_client, "recovery-supfail-b@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    user = await user_by_email(db_session, "recovery-supfail-b@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    old_provider = StubActionProvider(
        exception=ProviderError("late failure"),
        gate=True,
    )
    winner_provider = StubActionProvider()

    async with factory() as db_a:
        task_a = asyncio.create_task(
            generate_actions(
                db_a,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                old_provider,
            )
        )
        try:
            await old_provider.claimed.wait()
            document_uuid = uuid.UUID(document["id"])
            row_id = await db_session.scalar(
                select(DocumentActionSet.id).where(DocumentActionSet.document_id == document_uuid)
            )
            await db_session.execute(
                update(DocumentActionSet)
                .where(DocumentActionSet.id == row_id)
                .values(processing_started_at=stale_time())
            )
            await db_session.commit()

            async with factory() as db_b:
                winner_result, _ = await generate_actions(
                    db_b,
                    uuid.UUID(space["id"]),
                    document_uuid,
                    user.id,
                    winner_provider,
                )
            assert winner_result.status == "ready"

            old_provider.release.set()
            result_a, created_a = await task_a
            assert created_a is False
            assert result_a.status == "ready"

            row = await current_action_set(db_session, document_uuid)
            assert row.status == "ready"
            assert row.error_message is None
            assert len(row.actions) == 1
            assert row.actions[0].title == "Pay the invoice"
        finally:
            old_provider.release.set()


@pytest.mark.asyncio
async def test_analysis_ready_remains_idempotent(
    async_client: AsyncClient,
):
    token = await register_user(async_client, "recovery-idem-a@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubAnalysisProvider()
    install_analysis_provider(stub)

    first = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert first.status_code == 201
    second = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_actions_ready_remains_idempotent(
    async_client: AsyncClient,
):
    token = await register_user(async_client, "recovery-idem-b@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubActionProvider()
    install_action_provider(stub)

    first = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert first.status_code == 201
    second = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_analysis_stale_reclaim_is_scoped_to_owner(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    owner_token = await register_user(async_client, "recovery-owner-a@test.com")
    intruder_token = await register_user(async_client, "recovery-intruder-a@test.com")
    space = await create_space(async_client, owner_token)
    document = (
        await upload_pdf(async_client, owner_token, space["id"], ["alpha beta gamma"])
    ).json()
    old_attempt = uuid.uuid4()
    seeded = await seed_analysis(
        db_session,
        uuid.UUID(document["id"]),
        started_at=stale_time(),
        attempt_id=old_attempt,
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(intruder_token)
    )
    assert response.status_code == 404
    row = await current_analysis(db_session, uuid.UUID(document["id"]))
    assert row.status == "processing"
    assert row.processing_attempt_id == seeded.processing_attempt_id
    assert row.processing_started_at == seeded.processing_started_at


@pytest.mark.asyncio
async def test_actions_stale_reclaim_is_scoped_to_owner(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    owner_token = await register_user(async_client, "recovery-owner-b@test.com")
    intruder_token = await register_user(async_client, "recovery-intruder-b@test.com")
    space = await create_space(async_client, owner_token)
    document = (
        await upload_pdf(async_client, owner_token, space["id"], ["alpha beta gamma"])
    ).json()
    old_attempt = uuid.uuid4()
    seeded = await seed_action_set(
        db_session,
        uuid.UUID(document["id"]),
        started_at=stale_time(),
        attempt_id=old_attempt,
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(intruder_token)
    )
    assert response.status_code == 404
    row = await current_action_set(db_session, uuid.UUID(document["id"]))
    assert row.status == "processing"
    assert row.processing_attempt_id == seeded.processing_attempt_id
    assert row.processing_started_at == seeded.processing_started_at


@pytest.mark.asyncio
async def test_claim_predicate_rejects_ready_fresh_and_accepts_claimable(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Pin the CAS predicate directly against the lease helper (DB-level proof).

    The claim UPDATE must match ONLY: failed rows, stale processing rows, and
    NULL-lease processing rows of the exact target row. Ready and fresh
    processing rows must return no claim (None), and the row must be untouched.
    """
    token = await register_user(async_client, "recovery-predicate@test.com")
    space = await create_space(async_client, token)

    async def seeded(status: str, started_at, attempt_id):
        doc = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
        row = await seed_analysis(
            db_session,
            uuid.UUID(doc["id"]),
            started_at=started_at,
            attempt_id=attempt_id,
            status=status,
        )
        return row

    ready_row = await seeded("ready", None, None)
    fresh_row = await seeded("processing", datetime.now(UTC), uuid.uuid4())
    stale_row = await seeded("processing", stale_time(), uuid.uuid4())
    null_lease_row = await seeded("processing", None, uuid.uuid4())
    failed_row = await seeded("failed", None, None)

    ready_id, ready_doc_id = ready_row.id, ready_row.document_id
    fresh_id, fresh_doc_id = fresh_row.id, fresh_row.document_id
    fresh_attempt = fresh_row.processing_attempt_id
    fresh_started = fresh_row.processing_started_at
    stale_id, stale_doc_id = stale_row.id, stale_row.document_id
    stale_old_started = stale_row.processing_started_at
    null_id, null_doc_id = null_lease_row.id, null_lease_row.document_id
    failed_id, failed_doc_id = failed_row.id, failed_row.document_id

    claim_ready = await claim_generation(
        db_session, DocumentAnalysis, ready_id, provider="mock", model_name="m"
    )
    assert claim_ready is None
    assert (await current_analysis(db_session, ready_doc_id)).status == "ready"

    claim_fresh = await claim_generation(
        db_session, DocumentAnalysis, fresh_id, provider="mock", model_name="m"
    )
    assert claim_fresh is None
    fresh_after = await current_analysis(db_session, fresh_doc_id)
    assert fresh_after.status == "processing"
    assert fresh_after.processing_attempt_id == fresh_attempt
    assert fresh_after.processing_started_at == fresh_started

    claim_stale = await claim_generation(
        db_session, DocumentAnalysis, stale_id, provider="mock", model_name="m"
    )
    assert claim_stale is not None
    stale_attempt, stale_started = claim_stale
    assert stale_started > stale_old_started
    stale_after = await current_analysis(db_session, stale_doc_id)
    assert stale_after.processing_attempt_id == stale_attempt

    claim_null = await claim_generation(
        db_session, DocumentAnalysis, null_id, provider="mock", model_name="m"
    )
    assert claim_null is not None
    assert claim_null[0] == (await current_analysis(db_session, null_doc_id)).processing_attempt_id

    claim_failed = await claim_generation(
        db_session, DocumentAnalysis, failed_id, provider="mock", model_name="m"
    )
    assert claim_failed is not None
    assert (
        claim_failed[0] == (await current_analysis(db_session, failed_doc_id)).processing_attempt_id
    )


@pytest.mark.asyncio
async def test_terminal_completion_requires_own_attempt_token(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Pin terminal CAS ownership: only the active attempt may write ready/failed,
    and completion clears the lease fields (DB-level proof, no service involved)."""
    token = await register_user(async_client, "recovery-terminal@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    owner_attempt = uuid.uuid4()
    row = await seed_analysis(
        db_session,
        uuid.UUID(document["id"]),
        started_at=datetime.now(UTC),
        attempt_id=owner_attempt,
    )

    wrong_token = uuid.uuid4()
    row_id = row.id
    rejected = await complete_generation(
        db_session,
        DocumentAnalysis,
        row_id,
        wrong_token,
        status="ready",
        values={"error_message": None},
    )
    assert rejected is False
    after = await current_analysis(db_session, uuid.UUID(document["id"]))
    assert after.status == "processing"
    assert after.processing_attempt_id == owner_attempt
    assert after.processing_started_at is not None

    accepted = await complete_generation(
        db_session,
        DocumentAnalysis,
        row_id,
        owner_attempt,
        status="ready",
        values={"error_message": None},
    )
    assert accepted is True
    after = await current_analysis(db_session, uuid.UUID(document["id"]))
    await db_session.refresh(after)
    assert after.status == "ready"
    assert after.processing_started_at is None
    assert after.processing_attempt_id is None


@pytest.mark.asyncio
async def test_actions_completion_rolls_back_child_replacements_when_superseded(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    """Superseded action completion must roll back child replacement rows along
    with the parent CAS (child writes live in the same short transaction)."""
    token = await register_user(async_client, "recovery-childrollback@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    user = await user_by_email(db_session, "recovery-childrollback@test.com")
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    old_provider = StubActionProvider(
        result=ProviderDocumentActions(
            actions=[
                ProviderAction(
                    action_type="required_action",
                    title="SUPERSEDED CHILD",
                    description=None,
                    timing_text=None,
                    due_date=None,
                    source_ids=[f"chunk:{uuid.uuid4()}"],
                )
            ]
        ),
        gate=True,
    )
    winner_provider = StubActionProvider()

    async with factory() as db_a:
        task_a = asyncio.create_task(
            generate_actions(
                db_a,
                uuid.UUID(space["id"]),
                uuid.UUID(document["id"]),
                user.id,
                old_provider,
            )
        )
        try:
            await old_provider.claimed.wait()
            document_uuid = uuid.UUID(document["id"])
            row_id = await db_session.scalar(
                select(DocumentActionSet.id).where(DocumentActionSet.document_id == document_uuid)
            )
            await db_session.execute(
                update(DocumentActionSet)
                .where(DocumentActionSet.id == row_id)
                .values(processing_started_at=stale_time())
            )
            await db_session.commit()

            async with factory() as db_b:
                winner_result, _ = await generate_actions(
                    db_b,
                    uuid.UUID(space["id"]),
                    document_uuid,
                    user.id,
                    winner_provider,
                )
            assert winner_result.status == "ready"

            old_provider.release.set()
            result_a, _ = await task_a
            assert result_a.status == "ready"

            row = await current_action_set(db_session, document_uuid)
            assert row.status == "ready"
            assert [action.title for action in row.actions] == ["Pay the invoice"]
            assert all(action.title != "SUPERSEDED CHILD" for action in row.actions)
        finally:
            old_provider.release.set()
