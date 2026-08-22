"""Duplicate-upload rejection and stale-processing recovery regressions."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.infrastructure.models import Document
from tests.pdf_factory import text_pdf

SPACES_URL = "/knowledge-spaces"


async def register_user(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "TestPass1", "display_name": email.split("@")[0]},
    )
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_space(client: AsyncClient, token: str, name: str = "Research") -> dict:
    response = await client.post(SPACES_URL, json={"name": name}, headers=auth_header(token))
    assert response.status_code == 201
    return response.json()


async def upload_pdf(
    client: AsyncClient,
    token: str,
    space_id: str,
    filename: str = "evidence.pdf",
    text: str = "DocuMind retrieves evidence from private documents.",
):
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": (filename, text_pdf(text), "application/pdf")},
    )


@pytest.mark.asyncio
async def test_identical_file_in_same_space_is_rejected_with_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "dup-same@test.com")
    space = await create_space(async_client, token)

    first = await upload_pdf(async_client, token, space["id"])
    assert first.status_code == 201

    second = await upload_pdf(async_client, token, space["id"], filename="renamed.pdf")
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["existing_document_id"] == first.json()["id"]

    listing = await async_client.get(
        f"{SPACES_URL}/{space['id']}/documents", headers=auth_header(token)
    )
    assert len(listing.json()) == 1


@pytest.mark.asyncio
async def test_same_content_different_space_is_allowed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "dup-cross-space@test.com")
    contracts = await create_space(async_client, token, name="Contracts")
    research = await create_space(async_client, token, name="Research")

    first = await upload_pdf(async_client, token, contracts["id"])
    second = await upload_pdf(async_client, token, research["id"])

    assert first.status_code == 201
    assert second.status_code == 201


@pytest.mark.asyncio
async def test_different_content_same_space_is_allowed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "dup-different@test.com")
    space = await create_space(async_client, token)

    first = await upload_pdf(async_client, token, space["id"])
    second = await upload_pdf(
        async_client, token, space["id"], filename="other.pdf", text="Completely different words."
    )

    assert first.status_code == 201
    assert second.status_code == 201


@pytest.mark.asyncio
async def test_identical_content_for_other_users_is_allowed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    user_a = await register_user(async_client, "dup-user-a@test.com")
    user_b = await register_user(async_client, "dup-user-b@test.com")
    space_a = await create_space(async_client, user_a)
    space_b = await create_space(async_client, user_b)

    first = await upload_pdf(async_client, user_a, space_a["id"])
    second = await upload_pdf(async_client, user_b, space_b["id"])

    assert first.status_code == 201
    assert second.status_code == 201


@pytest.mark.asyncio
async def test_retry_reclaims_stale_processing_document(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """A PROCESSING claim left behind by a crash is atomically recoverable."""
    token = await register_user(async_client, "stale-reclaim@test.com")
    space = await create_space(async_client, token)
    upload = await upload_pdf(async_client, token, space["id"])
    document_id = upload.json()["id"]

    # Simulate a crash mid-processing: backdate the claim beyond the cutoff.
    cutoff_backdate = datetime.now(UTC) - timedelta(
        seconds=settings.document_stale_after_seconds + 60
    )
    result = await db_session.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one()
    document.processing_started_at = cutoff_backdate
    document.status = "processing"
    await db_session.commit()

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/documents/{document_id}/retry",
        headers=auth_header(token),
    )

    # The retry reclaims the stale claim and reprocesses to a terminal state.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ready", "failed"}


@pytest.mark.asyncio
async def test_retry_fresh_processing_document_conflicts(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "stale-fresh@test.com")
    space = await create_space(async_client, token)
    upload = await upload_pdf(async_client, token, space["id"])
    document_id = upload.json()["id"]

    result = await db_session.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one()
    document.processing_started_at = datetime.now(UTC)
    document.status = "processing"
    await db_session.commit()

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/documents/{document_id}/retry",
        headers=auth_header(token),
    )

    assert response.status_code == 409
