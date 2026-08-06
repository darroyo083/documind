import asyncio
import re
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.actions import generate_actions
from app.application.dependencies import get_action_provider
from app.domain.actions import (
    DocumentActionContext,
    ProviderAction,
    ProviderDocumentActions,
)
from app.domain.errors import ActionConflictError, ProviderError
from app.infrastructure.action_providers import DeterministicActionProvider
from app.infrastructure.models import (
    Document,
    DocumentAction,
    DocumentActionSet,
    DocumentChunk,
    DocumentStatus,
    User,
)
from app.infrastructure.providers import DeterministicEmbeddingProvider
from app.main import app
from tests.pdf_factory import page_pdf, text_pdf

SPACES_URL = "/knowledge-spaces"
EMBEDDING = DeterministicEmbeddingProvider(384)


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


async def create_space(client: AsyncClient, token: str, name: str = "Actions") -> dict:
    response = await client.post(SPACES_URL, json={"name": name}, headers=auth_header(token))
    assert response.status_code == 201
    return response.json()


async def upload_pdf(
    client: AsyncClient,
    token: str,
    space_id: str,
    pages: list[str],
):
    bytes_data = page_pdf(pages) if len(pages) > 1 else text_pdf(pages[0])
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": ("evidence.pdf", bytes_data, "application/pdf")},
    )


def actions_path(space_id: str, document_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/documents/{document_id}/actions"


def action_path(space_id: str, document_id: str, action_id: str) -> str:
    return f"{actions_path(space_id, document_id)}/{action_id}"


def default_provider_result(context: DocumentActionContext) -> ProviderDocumentActions:
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


class StubActionProvider:
    model_name = "stub-actions"

    def __init__(self, result=None, exception=None, empty=False, result_fn=None):
        self.calls = 0
        self.context = None
        self.result = result
        self.exception = exception
        self.empty = empty
        self.result_fn = result_fn

    async def generate_actions(
        self, context: DocumentActionContext
    ) -> ProviderDocumentActions | None:
        self.calls += 1
        self.context = context
        if self.exception is not None:
            raise self.exception
        if self.empty:
            return None
        if self.result_fn is not None:
            return self.result_fn(context)
        return self.result if self.result is not None else default_provider_result(context)


def install_provider(stub: StubActionProvider) -> None:
    app.dependency_overrides[get_action_provider] = lambda: stub


async def sets_for(db_session: AsyncSession, document_id: str) -> list[DocumentActionSet]:
    result = await db_session.execute(
        select(DocumentActionSet).where(DocumentActionSet.document_id == uuid.UUID(document_id))
    )
    return list(result.scalars().all())


async def first_chunk_id(db_session: AsyncSession, document_id: str) -> str:
    chunk_id = await db_session.scalar(
        select(DocumentChunk.id).where(DocumentChunk.document_id == uuid.UUID(document_id))
    )
    assert chunk_id is not None
    return str(chunk_id)


async def action_rows(db_session: AsyncSession, action_set_id: str) -> list[DocumentAction]:
    result = await db_session.execute(
        select(DocumentAction)
        .where(DocumentAction.action_set_id == uuid.UUID(action_set_id))
        .order_by(DocumentAction.position)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_actions_require_authentication(async_client: AsyncClient):
    response = await async_client.post(actions_path(str(uuid.uuid4()), str(uuid.uuid4())))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_actions_requires_authentication(async_client: AsyncClient):
    response = await async_client.get(actions_path(str(uuid.uuid4()), str(uuid.uuid4())))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_action_requires_authentication(async_client: AsyncClient):
    response = await async_client.patch(
        action_path(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())),
        json={"status": "completed"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_actions_hidden_from_other_users(async_client: AsyncClient):
    owner_token = await register_user(async_client, "actions-owner@test.com")
    intruder_token = await register_user(async_client, "actions-intruder@test.com")
    space = await create_space(async_client, owner_token)
    document = (
        await upload_pdf(async_client, owner_token, space["id"], ["alpha beta gamma"])
    ).json()

    path = actions_path(space["id"], document["id"])
    assert (await async_client.get(path, headers=auth_header(intruder_token))).status_code == 404
    assert (await async_client.post(path, headers=auth_header(intruder_token))).status_code == 404


@pytest.mark.asyncio
async def test_actions_of_another_space_same_user_returns_404(async_client: AsyncClient):
    token = await register_user(async_client, "actions-cross-space@test.com")
    space_a = await create_space(async_client, token, "Space A")
    space_b = await create_space(async_client, token, "Space B")
    document = (await upload_pdf(async_client, token, space_a["id"], ["private alpha"])).json()

    response = await async_client.post(
        actions_path(space_b["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_generate_actions_succeeds_and_persists(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-ok@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(async_client, token, space["id"], ["alpha beta gamma delta"])
    ).json()
    install_provider(StubActionProvider())

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["document_id"] == document["id"]
    assert payload["provider"] == "mock"
    assert payload["model"] == "stub-actions"
    action = payload["actions"][0]
    assert action["action_type"] == "deadline"
    assert action["title"] == "Pay the invoice"
    assert action["due_date"] == "2027-01-31"
    assert action["status"] == "pending"
    assert action["completed_at"] is None
    assert action["sources"][0]["page_number"] == 1
    assert action["sources"][0]["chunk_id"]
    assert "chunk:" not in action["sources"][0]["chunk_id"]

    rows = await sets_for(db_session, document["id"])
    assert len(rows) == 1
    assert rows[0].status == "ready"
    assert await action_rows(db_session, str(rows[0].id))

    fetched = await async_client.get(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["id"]
    assert fetched.json()["actions"] == payload["actions"]


@pytest.mark.asyncio
async def test_processing_document_is_rejected(async_client: AsyncClient, db_session: AsyncSession):
    token = await register_user(async_client, "actions-processing-doc@test.com")
    space = await create_space(async_client, token)
    processing = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="processing.pdf",
        storage_key="processing-actions.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.PROCESSING.value,
    )
    db_session.add(processing)
    await db_session.commit()
    await db_session.refresh(processing)

    response = await async_client.post(
        actions_path(space["id"], str(processing.id)), headers=auth_header(token)
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_failed_document_is_rejected(async_client: AsyncClient, db_session: AsyncSession):
    token = await register_user(async_client, "actions-failed-doc@test.com")
    space = await create_space(async_client, token)
    failed = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="failed.pdf",
        storage_key="failed-actions.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.FAILED.value,
        error_message="boom",
    )
    db_session.add(failed)
    await db_session.commit()
    await db_session.refresh(failed)

    response = await async_client.post(
        actions_path(space["id"], str(failed.id)), headers=auth_header(token)
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ready_document_without_chunks_is_rejected(
    async_client: AsyncClient, db_session: AsyncSession
):
    token = await register_user(async_client, "actions-nochunks@test.com")
    space = await create_space(async_client, token)
    empty = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="empty.pdf",
        storage_key="empty-actions.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.READY.value,
        page_count=1,
    )
    db_session.add(empty)
    await db_session.commit()
    await db_session.refresh(empty)

    response = await async_client.post(
        actions_path(space["id"], str(empty.id)), headers=auth_header(token)
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_processing_action_set_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-conflict@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    db_session.add(
        DocumentActionSet(
            document_id=uuid.UUID(document["id"]),
            status="processing",
            provider="mock",
            processing_started_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_existing_ready_set_is_idempotent(async_client: AsyncClient):
    token = await register_user(async_client, "actions-idempotent@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    stub = StubActionProvider()
    install_provider(stub)

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
async def test_failed_set_can_retry(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-retry@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubActionProvider(exception=ProviderError("temporary outage"))
    install_provider(stub)

    first = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert first.status_code == 502
    rows = await sets_for(db_session, document["id"])
    assert rows[0].status == "failed"
    assert rows[0].error_message == "temporary outage"

    stub.exception = None
    retry = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "ready"
    assert stub.calls == 2


@pytest.mark.asyncio
async def test_retry_replaces_failed_generated_actions(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-replace@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubActionProvider(exception=ProviderError("outage"))
    install_provider(stub)
    await async_client.post(actions_path(space["id"], document["id"]), headers=auth_header(token))
    rows = await sets_for(db_session, document["id"])
    failed_set_id = str(rows[0].id)
    assert await action_rows(db_session, failed_set_id) == []

    stub.exception = None
    await async_client.post(actions_path(space["id"], document["id"]), headers=auth_header(token))
    rows = await sets_for(db_session, document["id"])
    assert len(rows) == 1
    assert len(await action_rows(db_session, str(rows[0].id))) == 1


@pytest.mark.asyncio
async def test_retry_replaces_leftover_actions_without_unique_violation(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-leftover@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert created.status_code == 201

    rows = await sets_for(db_session, document["id"])
    row = rows[0]
    row.status = "failed"
    row.error_message = "simulated failure"
    await db_session.commit()

    retry = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "ready"
    assert len(retry.json()["actions"]) == 1
    refreshed = await sets_for(db_session, document["id"])
    assert len(refreshed) == 1
    assert len(await action_rows(db_session, str(refreshed[0].id))) == 1


@pytest.mark.asyncio
async def test_invalid_source_id_fails_and_persists_failed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-badsource@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="deadline",
                        title="Bad",
                        description=None,
                        timing_text="31 January 2027",
                        due_date="2027-01-31",
                        source_ids=["chunk:nonexistent"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    rows = await sets_for(db_session, document["id"])
    assert rows[0].status == "failed"
    assert rows[0].error_message is not None
    assert "unknown or unauthorized" in rows[0].error_message


@pytest.mark.asyncio
async def test_cross_document_source_reference_is_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-crossdoc@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    other = (await upload_pdf(async_client, token, space["id"], ["other evidence document"])).json()
    foreign_chunk_id = await first_chunk_id(db_session, other["id"])
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="reminder",
                        title="Foreign",
                        description=None,
                        timing_text=None,
                        due_date=None,
                        source_ids=[f"chunk:{foreign_chunk_id}"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_analysis_cannot_reference_another_users_chunk(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    other_token = await register_user(async_client, "other-actions-user@test.com")
    token = await register_user(async_client, "current-actions-user@test.com")
    other_space = await create_space(async_client, other_token)
    other_document = (
        await upload_pdf(async_client, other_token, other_space["id"], ["owner data"])
    ).json()
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["my private data"])).json()
    foreign_chunk_id = await first_chunk_id(db_session, other_document["id"])
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="required_action",
                        title="Foreign",
                        description=None,
                        timing_text=None,
                        due_date=None,
                        source_ids=[f"chunk:{foreign_chunk_id}"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_missing_source_ids_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "actions-nosource@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="reminder",
                        title="No sources",
                        description=None,
                        timing_text=None,
                        due_date=None,
                        source_ids=[],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_duplicate_source_ids_are_deduplicated(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-dup-src@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    real_chunk = await first_chunk_id(db_session, document["id"])
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="deadline",
                        title="Pay",
                        description=None,
                        timing_text="31 January 2027",
                        due_date="2027-01-31",
                        source_ids=[f"chunk:{real_chunk}", f"chunk:{real_chunk}"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    sources = response.json()["actions"][0]["sources"]
    assert len(sources) == 1


@pytest.mark.asyncio
async def test_empty_actions_are_valid(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-empty@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(StubActionProvider(result=ProviderDocumentActions(actions=[])))

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert response.json()["status"] == "ready"
    assert response.json()["actions"] == []


@pytest.mark.asyncio
async def test_empty_provider_response_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "actions-empty-prov@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(StubActionProvider(empty=True))

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_invalid_action_type_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "actions-badtype@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="invented_type",
                        title="Bad",
                        description=None,
                        timing_text=None,
                        due_date=None,
                        source_ids=[f"chunk:{uuid.uuid4()}"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert "invalid action type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_too_many_actions_rejected(async_client: AsyncClient, monkeypatch):
    from app.config import settings

    token = await register_user(async_client, "actions-many@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    monkeypatch.setattr(settings, "action_max_items", 1)
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="reminder",
                        title=f"Action {index}",
                        description=None,
                        timing_text=None,
                        due_date=None,
                        source_ids=[f"chunk:{uuid.uuid4()}"],
                    )
                    for index in range(3)
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Too many actions"


@pytest.mark.asyncio
async def test_oversized_title_rejected(async_client: AsyncClient, monkeypatch):
    from app.config import settings

    token = await register_user(async_client, "actions-long-title@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    monkeypatch.setattr(settings, "action_max_title_length", 10)
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="reminder",
                        title="This title is far too long for the configured limit",
                        description=None,
                        timing_text=None,
                        due_date=None,
                        source_ids=[f"chunk:{uuid.uuid4()}"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_invalid_due_date_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "actions-bad-date@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="deadline",
                        title="Bad date",
                        description=None,
                        timing_text="31 January 2027",
                        due_date="not-a-date",
                        source_ids=[f"chunk:{uuid.uuid4()}"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_partial_date_stays_null(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-partial@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    real_chunk = await first_chunk_id(db_session, document["id"])
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="reminder",
                        title="Renewal",
                        description=None,
                        timing_text="January 2027",
                        due_date=None,
                        source_ids=[f"chunk:{real_chunk}"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    action = response.json()["actions"][0]
    assert action["due_date"] is None
    assert action["timing_text"] == "January 2027"


@pytest.mark.asyncio
async def test_exact_due_date_normalized(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-exact@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    real_chunk = await first_chunk_id(db_session, document["id"])
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="deadline",
                        title="Pay",
                        description=None,
                        timing_text="Payment is due on 31 January 2027",
                        due_date=None,
                        source_ids=[f"chunk:{real_chunk}"],
                    )
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert response.json()["actions"][0]["due_date"] == "2027-01-31"


@pytest.mark.asyncio
async def test_context_orders_sources_and_scopes_document(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-context@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            ["Page one content", "Page two content", "Page three content"],
        )
    ).json()
    (await upload_pdf(async_client, token, space["id"], ["OTHER_DOC_MARKER"])).json()

    stub = StubActionProvider()
    install_provider(stub)
    await async_client.post(actions_path(space["id"], document["id"]), headers=auth_header(token))
    assert stub.context is not None
    pages = [source.page_number for source in stub.context.sources]
    assert pages == sorted(pages)
    assert "OTHER_DOC_MARKER" not in stub.context.render()


@pytest.mark.asyncio
async def test_context_overflow_rejected_not_truncated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    from app.config import settings

    token = await register_user(async_client, "actions-overflow@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            ["common_name " * 200],
        )
    ).json()
    monkeypatch.setattr(settings, "action_max_context_chars", 100)

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 422
    assert await sets_for(db_session, document["id"]) == []


@pytest.mark.asyncio
async def test_duplicate_actions_are_deduplicated(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-dup-items@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    real_chunk = await first_chunk_id(db_session, document["id"])
    install_provider(
        StubActionProvider(
            result=ProviderDocumentActions(
                actions=[
                    ProviderAction(
                        action_type="deadline",
                        title="Pay the invoice",
                        description=None,
                        timing_text="31 January 2027",
                        due_date="2027-01-31",
                        source_ids=[f"chunk:{real_chunk}"],
                    ),
                    ProviderAction(
                        action_type="deadline",
                        title="Pay the invoice",
                        description=None,
                        timing_text="31 January 2027",
                        due_date="2027-01-31",
                        source_ids=[f"chunk:{real_chunk}"],
                    ),
                ]
            )
        )
    )

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert len(response.json()["actions"]) == 1


@pytest.mark.asyncio
async def test_completion_flow(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-complete@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    action_id = created.json()["actions"][0]["id"]
    assert created.json()["actions"][0]["status"] == "pending"
    assert created.json()["actions"][0]["completed_at"] is None

    completed = await async_client.patch(
        action_path(space["id"], document["id"], action_id),
        json={"status": "completed"},
        headers=auth_header(token),
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None
    assert completed.json()["title"] == "Pay the invoice"

    fetched = await async_client.get(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert fetched.json()["actions"][0]["status"] == "completed"

    restored = await async_client.patch(
        action_path(space["id"], document["id"], action_id),
        json={"status": "pending"},
        headers=auth_header(token),
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "pending"
    assert restored.json()["completed_at"] is None


@pytest.mark.asyncio
async def test_completion_survives_unrelated_operations(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-survive@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    action_id = created.json()["actions"][0]["id"]
    await async_client.patch(
        action_path(space["id"], document["id"], action_id),
        json={"status": "completed"},
        headers=auth_header(token),
    )

    await async_client.post(
        f"{SPACES_URL}/{space['id']}/search",
        json={"query": "alpha"},
        headers=auth_header(token),
    )
    fetched = await async_client.get(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert fetched.json()["actions"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_patch_invalid_status_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "actions-badstatus@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    action_id = created.json()["actions"][0]["id"]

    response = await async_client.patch(
        action_path(space["id"], document["id"], action_id),
        json={"status": "banana"},
        headers=auth_header(token),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_rejects_extra_fields(async_client: AsyncClient):
    token = await register_user(async_client, "actions-extra@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    action_id = created.json()["actions"][0]["id"]

    response = await async_client.patch(
        action_path(space["id"], document["id"], action_id),
        json={"status": "completed", "title": "Hacked"},
        headers=auth_header(token),
    )
    assert response.status_code == 422
    fetched = await async_client.get(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert fetched.json()["actions"][0]["title"] == "Pay the invoice"
    assert fetched.json()["actions"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_patch_other_documents_action_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-other-doc@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    document_b = (await upload_pdf(async_client, token, space["id"], ["delta epsilon"])).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document_a["id"]), headers=auth_header(token)
    )
    action_id = created.json()["actions"][0]["id"]

    response = await async_client.patch(
        action_path(space["id"], document_b["id"], action_id),
        json={"status": "completed"},
        headers=auth_header(token),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_other_users_action_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    owner_token = await register_user(async_client, "actions-owner2@test.com")
    intruder_token = await register_user(async_client, "actions-intruder2@test.com")
    space = await create_space(async_client, owner_token)
    document = (
        await upload_pdf(async_client, owner_token, space["id"], ["alpha beta gamma"])
    ).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(owner_token)
    )
    action_id = created.json()["actions"][0]["id"]

    response = await async_client.patch(
        action_path(space["id"], document["id"], action_id),
        json={"status": "completed"},
        headers=auth_header(intruder_token),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_deleting_document_cascades_actions(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-cascade@example.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert created.status_code == 201
    rows = await sets_for(db_session, document["id"])
    action_count = await db_session.scalar(
        select(func.count())
        .select_from(DocumentAction)
        .where(DocumentAction.action_set_id == rows[0].id)
    )
    assert action_count == 1

    await async_client.delete(
        f"{SPACES_URL}/{space['id']}/documents/{document['id']}",
        headers=auth_header(token),
    )
    assert await sets_for(db_session, document["id"]) == []


@pytest.mark.asyncio
async def test_deleting_space_cascades_actions(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "actions-space-cascade@example.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(StubActionProvider())
    created = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert created.status_code == 201
    rows = await sets_for(db_session, document["id"])
    assert len(rows) == 1

    await async_client.delete(f"{SPACES_URL}/{space['id']}", headers=auth_header(token))
    assert await sets_for(db_session, document["id"]) == []
    assert await db_session.get(Document, uuid.UUID(document["id"])) is None
    orphans = await db_session.scalar(
        select(func.count())
        .select_from(DocumentAction)
        .where(DocumentAction.action_set_id == rows[0].id)
    )
    assert orphans == 0


@pytest.mark.asyncio
async def test_deterministic_provider_end_to_end_contract(
    async_client: AsyncClient,
):
    token = await register_user(async_client, "actions-det@example.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            ["Cancellation requires written notice at least 30 days in advance."],
        )
    ).json()

    response = await async_client.post(
        actions_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    actions = response.json()["actions"]
    assert any(
        action["action_type"] == "required_action"
        and action["title"] == "Send written cancellation notice"
        for action in actions
    )
    cancellation = next(action for action in actions if action["action_type"] == "required_action")
    assert cancellation["timing_text"] == "At least 30 days before cancellation"
    assert cancellation["due_date"] is None
    assert cancellation["sources"][0]["page_number"] == 1


@pytest.mark.asyncio
async def test_stable_source_ids(async_client: AsyncClient):
    token = await register_user(async_client, "actions-stable@example.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubActionProvider()
    install_provider(stub)
    await async_client.post(actions_path(space["id"], document["id"]), headers=auth_header(token))
    assert stub.context is not None
    pattern = re.compile(r"chunk:[0-9a-f-]{36}")
    for source in stub.context.sources:
        assert pattern.fullmatch(source.source_id)


@pytest.mark.asyncio
async def test_concurrent_generation_never_exposes_integrity_error(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
):
    token = await register_user(async_client, "actions-race@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    user = await db_session.scalar(select(User).where(User.email == "actions-race@test.com"))
    assert user is not None

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    provider = DeterministicActionProvider()
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

    outcome_names = []
    for result in results:
        if isinstance(result, Exception):
            assert isinstance(result, ActionConflictError)
            outcome_names.append("conflict")
        else:
            outcome_names.append("ready")
    assert "IntegrityError" not in outcome_names
    assert all(name in {"ready", "conflict"} for name in outcome_names)
    assert "ready" in outcome_names
    assert len(await sets_for(db_session, document["id"])) == 1
