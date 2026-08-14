
import pytest
from httpx import AsyncClient

from app.application.dependencies import get_embedding_provider
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


async def create_space(client: AsyncClient, token: str, name: str) -> dict:
    response = await client.post(SPACES_URL, json={"name": name}, headers=auth_header(token))
    assert response.status_code == 201
    return response.json()


async def upload_pdf(
    client: AsyncClient, token: str, space_id: str, text: str, filename: str = "doc.pdf"
):
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": (filename, text_pdf(text), "application/pdf")},
    )


class CountingEmbeddingProvider:
    model_name = "counting-test"
    dimension = 384

    def __init__(self):
        self.query_calls = 0
        self._inner = DeterministicEmbeddingProvider()

    async def embed_query(self, text):
        self.query_calls += 1
        return await self._inner.embed_query(text)

    async def embed_texts(self, texts):
        return await self._inner.embed_texts(texts)


@pytest.mark.asyncio
async def test_search_across_owned_spaces_with_metadata(async_client: AsyncClient):
    token = await register_user(async_client, "search-owner@test.com")
    space_a = await create_space(async_client, token, "Contracts")
    space_b = await create_space(async_client, token, "Invoices")
    await upload_pdf(
        async_client, token, space_a["id"], "the termination clause requires notice", "lease.pdf"
    )
    await upload_pdf(
        async_client, token, space_b["id"], "invoice total is forty dollars", "invoice.pdf"
    )

    response = await async_client.get(
        "/search", params={"q": "termination"}, headers=auth_header(token)
    )
    assert response.status_code == 200
    hits = response.json()
    assert hits
    top = hits[0]
    assert top["space_name"] == "Contracts"
    assert top["document_name"] == "lease.pdf"
    assert top["page_number"] == 1
    assert "termination" in top["excerpt"].lower()
    assert set(top.keys()) == {
        "chunk_id",
        "document_id",
        "document_name",
        "space_id",
        "space_name",
        "page_number",
        "excerpt",
        "score",
    }


@pytest.mark.asyncio
async def test_search_returns_other_users_nothing(async_client: AsyncClient):
    owner = await register_user(async_client, "search-a@test.com")
    other = await register_user(async_client, "search-b@test.com")
    space = await create_space(async_client, owner, "Private")
    await upload_pdf(async_client, owner, space["id"], "the termination clause requires notice")

    response = await async_client.get(
        "/search", params={"q": "termination"}, headers=auth_header(other)
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_space_filter_scopes_results(async_client: AsyncClient):
    token = await register_user(async_client, "search-filter@test.com")
    space_a = await create_space(async_client, token, "Contracts")
    space_b = await create_space(async_client, token, "Invoices")
    await upload_pdf(async_client, token, space_a["id"], "the termination clause requires notice")
    await upload_pdf(async_client, token, space_b["id"], "another termination clause exists here")

    response = await async_client.get(
        "/search",
        params={"q": "termination", "space_ids": space_a["id"]},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    hits = response.json()
    assert hits
    assert all(hit["space_id"] == space_a["id"] for hit in hits)


@pytest.mark.asyncio
async def test_search_foreign_space_filter_is_safe(async_client: AsyncClient):
    owner = await register_user(async_client, "search-fowner@test.com")
    other = await register_user(async_client, "search-fother@test.com")
    foreign_space = await create_space(async_client, owner, "Foreign")
    await upload_pdf(
        async_client, owner, foreign_space["id"], "the termination clause requires notice"
    )

    other_space = await create_space(async_client, other, "Own")
    await upload_pdf(
        async_client, other, other_space["id"], "the termination clause requires notice"
    )

    response = await async_client.get(
        "/search",
        params={"q": "termination", "space_ids": foreign_space["id"]},
        headers=auth_header(other),
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_excludes_failed_documents(async_client: AsyncClient):
    token = await register_user(async_client, "search-ready@test.com")
    space = await create_space(async_client, token, "Mixed")
    await upload_pdf(
        async_client, token, space["id"], "the termination clause requires notice", "good.pdf"
    )
    await upload_pdf(async_client, token, space["id"], " ", "scanned.pdf")

    response = await async_client.get(
        "/search", params={"q": "termination"}, headers=auth_header(token)
    )
    assert response.status_code == 200
    hits = response.json()
    assert hits
    assert all(hit["document_name"] != "scanned.pdf" for hit in hits)


@pytest.mark.asyncio
async def test_search_embeds_query_once(async_client: AsyncClient):
    token = await register_user(async_client, "search-once@test.com")
    space = await create_space(async_client, token, "Contracts")
    await upload_pdf(async_client, token, space["id"], "the termination clause requires notice")
    counter = CountingEmbeddingProvider()
    app.dependency_overrides[get_embedding_provider] = lambda: counter

    response = await async_client.get(
        "/search", params={"q": "termination"}, headers=auth_header(token)
    )
    assert response.status_code == 200
    assert counter.query_calls == 1


@pytest.mark.asyncio
async def test_search_empty_query_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "search-empty@test.com")
    response = await async_client.get("/search", params={"q": "   "}, headers=auth_header(token))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_query_length_limit(async_client: AsyncClient):
    token = await register_user(async_client, "search-long@test.com")
    response = await async_client.get(
        "/search", params={"q": "x" * 501}, headers=auth_header(token)
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_result_limit_bounded(async_client: AsyncClient):
    token = await register_user(async_client, "search-limit@test.com")
    space = await create_space(async_client, token, "Contracts")
    for index in range(5):
        await upload_pdf(
            async_client,
            token,
            space["id"],
            f"the termination clause requires notice number {index}",
            f"doc{index}.pdf",
        )

    response = await async_client.get(
        "/search", params={"q": "termination", "limit": 2}, headers=auth_header(token)
    )
    assert response.status_code == 200
    assert len(response.json()) <= 2


@pytest.mark.asyncio
async def test_search_no_result(async_client: AsyncClient):
    token = await register_user(async_client, "search-none@test.com")
    space = await create_space(async_client, token, "Contracts")
    await upload_pdf(async_client, token, space["id"], "the termination clause requires notice")

    response = await async_client.get(
        "/search", params={"q": "zzz_unrelated_token_qqq"}, headers=auth_header(token)
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_deterministic_ordering(async_client: AsyncClient):
    token = await register_user(async_client, "search-order@test.com")
    space = await create_space(async_client, token, "Contracts")
    await upload_pdf(async_client, token, space["id"], "the termination clause requires notice")
    await upload_pdf(async_client, token, space["id"], "termination penalties apply", "second.pdf")

    first = await async_client.get(
        "/search", params={"q": "termination"}, headers=auth_header(token)
    )
    second = await async_client.get(
        "/search", params={"q": "termination"}, headers=auth_header(token)
    )
    assert first.json() == second.json()


@pytest.mark.asyncio
async def test_search_per_document_cap(async_client: AsyncClient):
    token = await register_user(async_client, "search-cap@test.com")
    space = await create_space(async_client, token, "Contracts")
    long_text = "termination " * 400
    await upload_pdf(async_client, token, space["id"], long_text, "long.pdf")

    response = await async_client.get(
        "/search", params={"q": "termination"}, headers=auth_header(token)
    )
    assert response.status_code == 200
    hits = response.json()
    assert hits
    doc_ids = [hit["document_id"] for hit in hits]
    assert len(doc_ids) == len(set(doc_ids))
    from collections import Counter

    counts = Counter(doc_ids)
    assert max(counts.values()) <= 3
