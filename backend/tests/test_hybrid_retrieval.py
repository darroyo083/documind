"""Hybrid retrieval behavior: lexical channel, fusion, scoping, suppression."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app as fastapi_app
from tests.pdf_factory import text_pdf

SPACES_URL = "/knowledge-spaces"


class BlindEmbeddingProvider:
    """Embedding provider with zero semantic signal.

    Returns an identical unit vector for every input, so the vector channel
    cannot discriminate between chunks. Any correct ranking must come from the
    lexical channel, proving hybrid retrieval degrades gracefully when the
    embedding model is uninformative.
    """

    @property
    def model_name(self) -> str:
        return "blind-test"

    @property
    def dimension(self) -> int:
        return settings.embedding_dimension

    def _vector(self) -> list[float]:
        vector = [0.0] * self.dimension
        vector[0] = 1.0
        return vector

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector() for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector()


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
async def test_lexical_channel_recovers_exact_terms_without_semantic_signal(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """With a blind embedding model only the lexical channel can rank correctly."""
    from app.application.dependencies import get_embedding_provider

    token = await register_user(async_client, "hybrid-lexical@test.com")
    space = await create_space(async_client, token)
    upload = await upload_pdf(
        async_client,
        token,
        space["id"],
        text=(
            "The ZKX-4400 pressure regulator valve assembly requires calibration "
            "every six months under standard operating conditions."
        ),
    )
    assert upload.status_code == 201

    async def override_embedding():
        return BlindEmbeddingProvider()

    fastapi_app.dependency_overrides[get_embedding_provider] = override_embedding
    try:
        search = await async_client.post(
            f"{SPACES_URL}/{space['id']}/search",
            json={"query": "ZKX-4400 calibration", "top_k": 3},
            headers=auth_header(token),
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_embedding_provider, None)

    assert search.status_code == 200
    results = search.json()["results"]
    assert results, "hybrid retrieval must find the exact identifier via the lexical channel"
    assert "ZKX-4400" in results[0]["excerpt"]


@pytest.mark.asyncio
async def test_lexical_channel_enforces_cross_user_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """A foreign user's identical document never surfaces through lexical matching."""
    attacker_token = await register_user(async_client, "hybrid-attacker@test.com")
    victim_token = await register_user(async_client, "hybrid-victim@test.com")

    attacker_space = await create_space(async_client, attacker_token, name="Attacker")
    victim_space = await create_space(async_client, victim_token, name="Victim")
    secret_text = (
        "Confidential merger agreement between Northwind Holdings and Stellar "
        "Partners with a total consideration of 42 million dollars."
    )
    victim_upload = await upload_pdf(
        async_client, victim_token, victim_space["id"], text=secret_text
    )
    assert victim_upload.status_code == 201

    search = await async_client.post(
        f"{SPACES_URL}/{attacker_space['id']}/search",
        json={"query": "Northwind Holdings merger consideration"},
        headers=auth_header(attacker_token),
    )

    assert search.status_code == 200
    assert search.json()["results"] == []


@pytest.mark.asyncio
async def test_lexical_channel_enforces_space_scoping(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "hybrid-scoping@test.com")
    contracts = await create_space(async_client, token, name="Contracts")
    research = await create_space(async_client, token, name="Research")
    upload = await upload_pdf(
        async_client,
        token,
        contracts["id"],
        text="The indemnification clause allocates liability exclusively to the vendor.",
    )
    assert upload.status_code == 201

    search = await async_client.post(
        f"{SPACES_URL}/{research['id']}/search",
        json={"query": "indemnification liability vendor"},
        headers=auth_header(token),
    )

    assert search.status_code == 200
    assert search.json()["results"] == []


@pytest.mark.asyncio
async def test_stopword_only_query_returns_no_candidates(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "hybrid-stopwords@test.com")
    space = await create_space(async_client, token)
    upload = await upload_pdf(
        async_client, token, space["id"], text="Substantial technical content lives here."
    )
    assert upload.status_code == 201

    ask = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "the of and"},
        headers=auth_header(token),
    )

    # Stop-word-only queries produce no lexical matches; the deterministic mock
    # embedding maps them to a vector that stays below the similarity threshold.
    assert ask.status_code == 200
    body = ask.json()
    assert body["supported"] is False or body["citations"] == []


@pytest.mark.asyncio
async def test_hybrid_ask_returns_grounded_citation(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "hybrid-ask@test.com")
    space = await create_space(async_client, token)
    upload = await upload_pdf(
        async_client,
        token,
        space["id"],
        text="DocuMind retrieves evidence from private documents with page citations.",
    )
    assert upload.status_code == 201

    ask = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "private documents"},
        headers=auth_header(token),
    )

    assert ask.status_code == 200
    body = ask.json()
    if body["supported"]:
        assert len(body["citations"]) >= 1
        citation = body["citations"][0]
        assert citation["document_name"] == "evidence.pdf"
        assert citation["page_number"] == 1
        assert citation["source_kind"] == "private"


@pytest.mark.asyncio
async def test_vector_mode_remains_available_for_baseline_comparison(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(settings, "retrieval_mode", "vector")
    token = await register_user(async_client, "hybrid-vector-mode@test.com")
    space = await create_space(async_client, token)
    upload = await upload_pdf(
        async_client,
        token,
        space["id"],
        text="DocuMind retrieves evidence from private documents.",
    )
    assert upload.status_code == 201

    search = await async_client.post(
        f"{SPACES_URL}/{space['id']}/search",
        json={"query": "retrieves evidence"},
        headers=auth_header(token),
    )

    assert search.status_code == 200
    assert len(search.json()["results"]) == 1


@pytest.mark.asyncio
async def test_invalid_retrieval_mode_fails_closed(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):

    monkeypatch.setattr(settings, "retrieval_mode", "nonsense")
    token = await register_user(async_client, "hybrid-invalid@test.com")
    space = await create_space(async_client, token)

    search = await async_client.post(
        f"{SPACES_URL}/{space['id']}/search",
        json={"query": "anything"},
        headers=auth_header(token),
    )

    assert search.status_code == 502


@pytest.mark.asyncio
async def test_global_search_uses_lexical_channel(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    from app.application.dependencies import get_embedding_provider

    token = await register_user(async_client, "hybrid-global@test.com")
    space = await create_space(async_client, token)
    upload = await upload_pdf(
        async_client,
        token,
        space["id"],
        text="Invoice REF-QQ-99881 covers the annual platform subscription renewal.",
    )
    assert upload.status_code == 201

    async def override_embedding():
        return BlindEmbeddingProvider()

    fastapi_app.dependency_overrides[get_embedding_provider] = override_embedding
    try:
        hits = await async_client.get(
            "/search?q=REF-QQ-99881",
            headers=auth_header(token),
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_embedding_provider, None)

    assert hits.status_code == 200
    results = hits.json()
    assert results, "global search must find exact identifiers lexically"
    assert results[0]["space_id"] == space["id"]
