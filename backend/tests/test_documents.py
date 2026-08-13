import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dependencies import get_answer_provider
from app.domain.rag import GeneratedAnswer
from app.infrastructure.models import Document, DocumentChunk
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
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_space(client: AsyncClient, token: str, name: str = "Research") -> dict:
    response = await client.post(
        SPACES_URL,
        json={"name": name},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    return response.json()


async def upload_pdf(
    client: AsyncClient,
    token: str,
    space_id: str,
    text: str = "DocuMind retrieves evidence from private documents.",
):
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": ("evidence.pdf", text_pdf(text), "application/pdf")},
    )


@pytest.mark.asyncio
async def test_upload_list_get_and_delete_document(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "documents@test.com")
    space = await create_space(async_client, token)

    upload = await upload_pdf(async_client, token, space["id"])
    assert upload.status_code == 201
    document = upload.json()
    assert document["original_filename"] == "evidence.pdf"
    assert document["status"] == "ready"
    assert document["page_count"] == 1
    assert document["error_message"] is None

    chunk_count = await db_session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == uuid.UUID(document["id"]))
    )
    assert chunk_count == 1

    listing = await async_client.get(
        f"{SPACES_URL}/{space['id']}/documents", headers=auth_header(token)
    )
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [document["id"]]

    detail = await async_client.get(
        f"{SPACES_URL}/{space['id']}/documents/{document['id']}",
        headers=auth_header(token),
    )
    assert detail.status_code == 200

    deleted = await async_client.delete(
        f"{SPACES_URL}/{space['id']}/documents/{document['id']}",
        headers=auth_header(token),
    )
    assert deleted.status_code == 204
    assert await db_session.get(Document, uuid.UUID(document["id"])) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "media_type"),
    [
        ("notes.txt", b"not a pdf", "text/plain"),
        ("fake.pdf", b"not a pdf", "application/pdf"),
    ],
)
async def test_upload_rejects_non_pdf_content(
    async_client: AsyncClient,
    filename: str,
    content: bytes,
    media_type: str,
):
    token = await register_user(async_client, f"invalid-{filename}@test.com")
    space = await create_space(async_client, token)
    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/documents",
        headers=auth_header(token),
        files={"file": (filename, content, media_type)},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_enforces_configured_size_limit(async_client: AsyncClient, monkeypatch):
    from app.config import settings

    token = await register_user(async_client, "oversized@test.com")
    space = await create_space(async_client, token)
    monkeypatch.setattr(settings, "max_upload_size_mb", 0)
    response = await upload_pdf(async_client, token, space["id"])
    assert response.status_code == 422
    assert "no larger than 0 MB" in response.json()["detail"]


@pytest.mark.asyncio
async def test_textless_pdf_is_recorded_as_failed(async_client: AsyncClient):
    token = await register_user(async_client, "textless@test.com")
    space = await create_space(async_client, token)
    response = await upload_pdf(async_client, token, space["id"], " ")
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["failure_code"] == "no_extractable_text"

    listing = await async_client.get(
        f"{SPACES_URL}/{space['id']}/documents", headers=auth_header(token)
    )
    assert listing.status_code == 200
    assert listing.json()[0]["status"] == "failed"
    assert "text" in listing.json()[0]["error_message"].lower()


@pytest.mark.asyncio
async def test_document_routes_hide_other_users_resources(async_client: AsyncClient):
    owner_token = await register_user(async_client, "document-owner@test.com")
    intruder_token = await register_user(async_client, "document-intruder@test.com")
    space = await create_space(async_client, owner_token)
    document = (await upload_pdf(async_client, owner_token, space["id"])).json()
    intruder_headers = auth_header(intruder_token)

    assert (
        await async_client.get(f"{SPACES_URL}/{space['id']}/documents", headers=intruder_headers)
    ).status_code == 404
    assert (
        await async_client.get(
            f"{SPACES_URL}/{space['id']}/documents/{document['id']}",
            headers=intruder_headers,
        )
    ).status_code == 404
    assert (
        await async_client.delete(
            f"{SPACES_URL}/{space['id']}/documents/{document['id']}",
            headers=intruder_headers,
        )
    ).status_code == 404
    assert (
        await async_client.post(
            f"{SPACES_URL}/{space['id']}/search",
            json={"query": "private"},
            headers=intruder_headers,
        )
    ).status_code == 404
    assert (
        await async_client.post(
            f"{SPACES_URL}/{space['id']}/ask",
            json={"question": "What is private?"},
            headers=intruder_headers,
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_deleting_space_removes_stored_documents(async_client: AsyncClient, tmp_path):
    token = await register_user(async_client, "space-cleanup@test.com")
    space = await create_space(async_client, token)
    upload = await upload_pdf(async_client, token, space["id"])
    assert upload.status_code == 201
    assert len(list((tmp_path / "uploads").glob("*.pdf"))) == 1

    deleted = await async_client.delete(f"{SPACES_URL}/{space['id']}", headers=auth_header(token))
    assert deleted.status_code == 204
    assert list((tmp_path / "uploads").glob("*.pdf")) == []


@pytest.mark.asyncio
async def test_search_and_answer_include_verified_page_citations(async_client: AsyncClient):
    token = await register_user(async_client, "retrieval@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            "DocuMind protects private documents with strict ownership isolation.",
        )
    ).json()

    search = await async_client.post(
        f"{SPACES_URL}/{space['id']}/search",
        json={"query": "ownership isolation"},
        headers=auth_header(token),
    )
    assert search.status_code == 200
    result = search.json()["results"][0]
    assert result["document_id"] == document["id"]
    assert result["document_name"] == "evidence.pdf"
    assert result["page_number"] == 1
    assert result["source_kind"] == "private"
    assert result["source_id"].startswith("private:")

    answer = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "How are private documents protected?"},
        headers=auth_header(token),
    )
    assert answer.status_code == 200
    assert answer.json()["supported"] is True
    assert answer.json()["citations"][0]["source_kind"] == "private"
    assert answer.json()["citations"][0]["source_id"].startswith("private:")


@pytest.mark.asyncio
async def test_ask_returns_insufficient_context_without_results(async_client: AsyncClient):
    token = await register_user(async_client, "insufficient@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "Oranges contain vitamin C.")

    answer = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "quasarxyz"},
        headers=auth_header(token),
    )
    assert answer.status_code == 200
    assert answer.json()["supported"] is False
    assert answer.json()["citations"] == []


@pytest.mark.asyncio
async def test_ask_rejects_provider_citations_outside_retrieved_context(
    async_client: AsyncClient,
):
    class FabricatingAnswerProvider:
        @property
        def model_name(self) -> str:
            return "fabricating-test"

        async def answer(self, question, context):
            return GeneratedAnswer("Invented answer", True, ["chunk:not-retrieved"])

    token = await register_user(async_client, "fabrication@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "Reliable evidence is available here.")
    app.dependency_overrides[get_answer_provider] = FabricatingAnswerProvider

    answer = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "What evidence is available?"},
        headers=auth_header(token),
    )
    assert answer.status_code == 502
    assert answer.json()["detail"] == "Answer provider returned unverifiable citations"
