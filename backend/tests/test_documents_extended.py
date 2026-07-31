import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dependencies import get_answer_provider, get_embedding_provider
from app.domain.errors import ProviderError
from app.domain.rag import GeneratedAnswer
from app.infrastructure.models import Document, DocumentChunk
from app.infrastructure.providers import DeterministicEmbeddingProvider
from app.main import app
from tests.pdf_factory import text_pdf

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
    text: str = "alpha beta gamma delta",
):
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": ("evidence.pdf", text_pdf(text), "application/pdf")},
    )


async def chunk_count_for(db_session: AsyncSession, document_id: str) -> int:
    return await db_session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == uuid.UUID(document_id))
    )


@pytest.mark.asyncio
async def test_upload_requires_authentication(async_client: AsyncClient):
    response = await async_client.post(
        f"{SPACES_URL}/{uuid.uuid4()}/documents",
        files={"file": ("evidence.pdf", text_pdf("alpha"), "application/pdf")},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_to_another_users_space_returns_404(async_client: AsyncClient):
    owner_token = await register_user(async_client, "space-owner-ext@test.com")
    intruder_token = await register_user(async_client, "space-intruder-ext@test.com")
    space = await create_space(async_client, owner_token)

    response = await upload_pdf(async_client, intruder_token, space["id"])
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_empty_file_is_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "empty-file-ext@test.com")
    space = await create_space(async_client, token)

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/documents",
        headers=auth_header(token),
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_embedding_failure_leaves_no_file_or_chunks(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    class FailingEmbeddingProvider:
        model_name = "failing-test"
        dimension = 384

        async def embed_texts(self, texts):
            raise ProviderError("simulated embedding outage")

        async def embed_query(self, text):
            raise ProviderError("simulated embedding outage")

    token = await register_user(async_client, "embed-fail-ext@test.com")
    space = await create_space(async_client, token)
    app.dependency_overrides[get_embedding_provider] = FailingEmbeddingProvider

    response = await upload_pdf(async_client, token, space["id"])
    assert response.status_code == 502
    assert response.json()["detail"] == "simulated embedding outage"

    listing = await async_client.get(
        f"{SPACES_URL}/{space['id']}/documents", headers=auth_header(token)
    )
    assert listing.status_code == 200
    documents = listing.json()
    assert documents[0]["status"] == "failed"
    assert documents[0]["error_message"] == "simulated embedding outage"
    assert await chunk_count_for(db_session, documents[0]["id"]) == 0
    assert list((tmp_path / "uploads").glob("*.pdf")) == []


@pytest.mark.asyncio
async def test_retrieval_orders_by_similarity_and_filters_threshold(
    async_client: AsyncClient,
):
    token = await register_user(async_client, "ordering-ext@test.com")
    space = await create_space(async_client, token)
    document_a = (
        await upload_pdf(async_client, token, space["id"], "alpha beta gamma delta")
    ).json()
    await upload_pdf(async_client, token, space["id"], "alpha")

    search = await async_client.post(
        f"{SPACES_URL}/{space['id']}/search",
        json={"query": "beta gamma delta", "top_k": 5},
        headers=auth_header(token),
    )
    assert search.status_code == 200
    results = search.json()["results"]
    assert len(results) == 1
    assert results[0]["document_id"] == document_a["id"]
    assert results[0]["score"] > 0.8


@pytest.mark.asyncio
async def test_retrieval_top_k_limits_results(async_client: AsyncClient):
    token = await register_user(async_client, "topk-ext@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(
        async_client,
        token,
        space["id"],
        " ".join(["fragment"] * 300),
    )

    search = await async_client.post(
        f"{SPACES_URL}/{space['id']}/search",
        json={"query": "fragment", "top_k": 2},
        headers=auth_header(token),
    )
    assert search.status_code == 200
    assert len(search.json()["results"]) == 2


@pytest.mark.asyncio
async def test_retrieval_rejects_top_k_above_configured_maximum(async_client: AsyncClient):
    token = await register_user(async_client, "max-topk-ext@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")

    search = await async_client.post(
        f"{SPACES_URL}/{space['id']}/search",
        json={"query": "alpha", "top_k": 999},
        headers=auth_header(token),
    )
    assert search.status_code == 422


@pytest.mark.asyncio
async def test_retrieval_excludes_processing_and_failed_documents(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "status-filter-ext@test.com")
    space = await create_space(async_client, token)
    ready_document = (
        await upload_pdf(async_client, token, space["id"], "fragment fragment")
    ).json()
    await upload_pdf(async_client, token, space["id"], "   ")
    processing_document = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="processing.pdf",
        storage_key="processing-storage.pdf",
        media_type="application/pdf",
        file_size=1,
        status="processing",
    )
    db_session.add(processing_document)
    await db_session.commit()
    await db_session.refresh(processing_document)
    db_session.add(
        DocumentChunk(
            document_id=processing_document.id,
            page_number=1,
            chunk_index=0,
            content="fragment",
            character_count=8,
            embedding=await EMBEDDING.embed_query("fragment"),
        )
    )
    await db_session.commit()

    search = await async_client.post(
        f"{SPACES_URL}/{space['id']}/search",
        json={"query": "fragment"},
        headers=auth_header(token),
    )
    assert search.status_code == 200
    result_ids = {result["document_id"] for result in search.json()["results"]}
    assert ready_document["id"] in result_ids
    assert str(processing_document.id) not in result_ids


@pytest.mark.asyncio
async def test_same_user_cannot_search_across_spaces(async_client: AsyncClient):
    token = await register_user(async_client, "cross-space-ext@test.com")
    space_a = await create_space(async_client, token, "Space A")
    space_b = await create_space(async_client, token, "Space B")
    await upload_pdf(async_client, token, space_a["id"], "private evidence alpha")

    search_b = await async_client.post(
        f"{SPACES_URL}/{space_b['id']}/search",
        json={"query": "private evidence alpha"},
        headers=auth_header(token),
    )
    assert search_b.status_code == 200
    assert search_b.json()["results"] == []

    ask_b = await async_client.post(
        f"{SPACES_URL}/{space_b['id']}/ask",
        json={"question": "What is the private evidence?"},
        headers=auth_header(token),
    )
    assert ask_b.status_code == 200
    assert ask_b.json()["supported"] is False
    assert ask_b.json()["citations"] == []


@pytest.mark.asyncio
async def test_delete_document_removes_file_and_chunks(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    token = await register_user(async_client, "delete-file-ext@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"])).json()
    assert len(list((tmp_path / "uploads").glob("*.pdf"))) == 1
    assert await chunk_count_for(db_session, document["id"]) == 1

    deleted = await async_client.delete(
        f"{SPACES_URL}/{space['id']}/documents/{document['id']}",
        headers=auth_header(token),
    )
    assert deleted.status_code == 204
    assert list((tmp_path / "uploads").glob("*.pdf")) == []
    assert await db_session.get(Document, uuid.UUID(document["id"])) is None
    assert await chunk_count_for(db_session, document["id"]) == 0


@pytest.mark.asyncio
async def test_supported_answer_without_citations_is_rejected(async_client: AsyncClient):
    class NoCitationProvider:
        @property
        def model_name(self) -> str:
            return "no-citation-test"

        async def answer(self, question, context):
            return GeneratedAnswer("Confident answer", True, [])

    token = await register_user(async_client, "no-citation-ext@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta gamma")
    app.dependency_overrides[get_answer_provider] = NoCitationProvider

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "What is alpha?"},
        headers=auth_header(token),
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Answer provider returned unverifiable citations"


@pytest.mark.asyncio
async def test_duplicate_citations_are_deduplicated(async_client: AsyncClient):
    class DuplicateCitationProvider:
        @property
        def model_name(self) -> str:
            return "duplicate-citation-test"

        async def answer(self, question, context):
            first = context[0]
            return GeneratedAnswer("Grounded answer", True, [first.source_id, first.source_id])

    token = await register_user(async_client, "duplicate-cit-ext@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta gamma")
    app.dependency_overrides[get_answer_provider] = DuplicateCitationProvider

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "What is alpha?"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    answer = response.json()
    assert answer["supported"] is True
    assert len(answer["citations"]) == 1
    assert answer["answer"] == "Grounded answer"


@pytest.mark.asyncio
async def test_provider_error_returns_controlled_response(async_client: AsyncClient):
    class ThrowingProvider:
        @property
        def model_name(self) -> str:
            return "throwing-test"

        async def answer(self, question, context):
            raise ProviderError("simulated provider outage")

    token = await register_user(async_client, "provider-error-ext@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta gamma")
    app.dependency_overrides[get_answer_provider] = ThrowingProvider

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "What is alpha?"},
        headers=auth_header(token),
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "simulated provider outage"
