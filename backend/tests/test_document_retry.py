import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dependencies import get_embedding_provider
from app.domain.errors import ProviderError
from app.infrastructure.models import Document
from app.infrastructure.providers import DeterministicEmbeddingProvider
from app.main import app
from tests.pdf_factory import text_pdf

SPACES_URL = "/knowledge-spaces"


async def register_user(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "TestPass1", "display_name": email.split("@")[0]},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_space(client: AsyncClient, token: str, name: str = "Retry") -> dict:
    response = await client.post(SPACES_URL, json={"name": name}, headers=auth_header(token))
    assert response.status_code == 201
    return response.json()


async def upload_pdf(client: AsyncClient, token: str, space_id: str, text: str = "alpha beta"):
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": ("evidence.pdf", text_pdf(text), "application/pdf")},
    )


def retry_path(space_id: str, document_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/documents/{document_id}/retry"


@pytest.mark.asyncio
async def test_retry_failed_document_reprocesses_without_duplicate(
    async_client: AsyncClient, db_session: AsyncSession
):
    class FlakyEmbeddingProvider:
        model_name = "flaky-test"
        dimension = 384

        def __init__(self):
            self.calls = 0
            self._inner = DeterministicEmbeddingProvider()

        async def embed_texts(self, texts):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("transient embedding outage")
            return await self._inner.embed_texts(texts)

        async def embed_query(self, text):
            return await self._inner.embed_query(text)

    token = await register_user(async_client, "retry-flaky@test.com")
    space = await create_space(async_client, token)
    flaky = FlakyEmbeddingProvider()
    app.dependency_overrides[get_embedding_provider] = lambda: flaky

    uploaded = await upload_pdf(async_client, token, space["id"])
    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["status"] == "failed"
    assert document["failure_code"] == "processing_failed"
    document_id = document["id"]

    retried = await async_client.post(
        retry_path(space["id"], document_id), headers=auth_header(token)
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "ready"
    assert retried.json()["failure_code"] is None

    count = await db_session.scalar(
        select(Document).where(Document.knowledge_space_id == uuid.UUID(space["id"]))
    )
    assert count is not None
    rows = list(
        (
            await db_session.execute(
                select(Document).where(Document.knowledge_space_id == uuid.UUID(space["id"]))
            )
        ).scalars()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_retry_ready_document_conflicts(async_client: AsyncClient):
    token = await register_user(async_client, "retry-ready@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"])).json()
    assert document["status"] == "ready"

    response = await async_client.post(
        retry_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_retry_cross_user_returns_404(async_client: AsyncClient):
    owner = await register_user(async_client, "retry-owner@test.com")
    other = await register_user(async_client, "retry-other@test.com")
    space = await create_space(async_client, owner)
    document = (await upload_pdf(async_client, owner, space["id"])).json()

    response = await async_client.post(
        retry_path(space["id"], document["id"]), headers=auth_header(other)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_retry_textless_document_stays_failed_without_duplicate(
    async_client: AsyncClient, db_session: AsyncSession
):
    token = await register_user(async_client, "retry-textless@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], " ")).json()
    assert document["status"] == "failed"
    assert document["failure_code"] == "no_extractable_text"

    response = await async_client.post(
        retry_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["failure_code"] == "no_extractable_text"

    rows = list(
        (
            await db_session.execute(
                select(Document).where(Document.knowledge_space_id == uuid.UUID(space["id"]))
            )
        ).scalars()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_retry_processsing_document_conflicts(
    async_client: AsyncClient, db_session: AsyncSession
):
    token = await register_user(async_client, "retry-processing@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], " ")).json()
    document_id = document["id"]

    row = await db_session.scalar(select(Document).where(Document.id == uuid.UUID(document_id)))
    assert row is not None
    row.status = "processing"
    row.error_message = None
    await db_session.commit()

    response = await async_client.post(
        retry_path(space["id"], document_id), headers=auth_header(token)
    )
    assert response.status_code == 409
