import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dependencies import get_answer_provider
from app.application.reference import import_reference_document
from app.application.retrieval import retrieve_chunks
from app.domain.errors import ProviderError, TextExtractionError
from app.domain.rag import GeneratedAnswer, KnowledgeScope, parse_knowledge_scope
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    KnowledgeSpace,
    ReferenceDocument,
    ReferenceDocumentChunk,
)
from app.infrastructure.providers import DeterministicEmbeddingProvider
from app.main import app
from tests.pdf_factory import page_pdf, text_pdf

SPACES_URL = "/knowledge-spaces"
EMBEDDING = DeterministicEmbeddingProvider(384)


@pytest.fixture(autouse=True)
async def _clean_reference_corpus(db_session: AsyncSession):
    """Each test starts with an empty reference corpus (session-scoped test DB)."""
    await db_session.execute(delete(ReferenceDocument))
    await db_session.commit()
    yield


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


async def create_space(client: AsyncClient, token: str, name: str = "Space") -> dict:
    response = await client.post(SPACES_URL, json={"name": name}, headers=auth_header(token))
    assert response.status_code == 201
    return response.json()


async def upload_pdf(
    client: AsyncClient,
    token: str,
    space_id: str,
    filename: str,
    text: str,
):
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": (filename, text_pdf(text), "application/pdf")},
    )


async def write_pdf(tmp_path: Path, filename: str, text: str) -> Path:
    path = tmp_path / filename
    path.write_bytes(text_pdf(text))
    return path


async def write_pages_pdf(tmp_path: Path, filename: str, pages: list[str]) -> Path:
    path = tmp_path / filename
    path.write_bytes(page_pdf(pages))
    return path


class FailingEmbeddingProvider:
    model_name = "failing-test"
    dimension = 384

    async def embed_texts(self, texts):
        raise ProviderError("simulated embedding outage")

    async def embed_query(self, text):
        raise ProviderError("simulated embedding outage")


async def reference_count(db_session: AsyncSession) -> int:
    count = await db_session.scalar(select(func.count()).select_from(ReferenceDocument))
    assert count is not None
    return count


async def chunks_for(db_session: AsyncSession, reference_id: str) -> list[ReferenceDocumentChunk]:
    result = await db_session.execute(
        select(ReferenceDocumentChunk)
        .where(ReferenceDocumentChunk.reference_document_id == uuid.UUID(reference_id))
        .order_by(ReferenceDocumentChunk.page_number, ReferenceDocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


class SpoofAnswerProvider:
    model_name = "spoof-test"

    def __init__(self, citation_ids: list[str]):
        self.citation_ids = citation_ids

    async def answer(self, question, context):
        return GeneratedAnswer("Grounded answer", True, self.citation_ids)


class CiteAllProvider:
    model_name = "cite-all-test"

    async def answer(self, question, context):
        return GeneratedAnswer(
            "Grounded answer", True, [candidate.source_id for candidate in context]
        )


def install_answer_provider(spoof) -> None:
    app.dependency_overrides[get_answer_provider] = lambda: spoof


# ---- Import ----


@pytest.mark.asyncio
async def test_reference_import_persists_document_and_chunks(db_session: AsyncSession, tmp_path):
    path = await write_pdf(
        tmp_path, "guide.pdf", "Insurance terminology guide REFERENCE-INSURANCE-2026."
    )
    document, created = await import_reference_document(
        db_session, path, "Insurance Terminology", EMBEDDING
    )
    assert created is True
    assert document.status == "ready"
    assert document.title == "Insurance Terminology"
    assert document.original_filename == "guide.pdf"
    assert document.page_count == 1
    assert len(document.content_sha256) == 64

    chunks = await chunks_for(db_session, str(document.id))
    assert len(chunks) == 1
    assert chunks[0].page_number == 1
    assert chunks[0].chunk_index == 0
    assert "REFERENCE-INSURANCE-2026" in chunks[0].content
    assert len(chunks[0].embedding) == 384


@pytest.mark.asyncio
async def test_reference_import_multi_page_preserves_order(db_session: AsyncSession, tmp_path):
    path = await write_pages_pdf(
        tmp_path,
        "multi.pdf",
        ["Page one REFERENCE-A", "Page two REFERENCE-B", "Page three REFERENCE-C"],
    )
    document, created = await import_reference_document(db_session, path, "Multi", EMBEDDING)
    assert created is True
    assert document.page_count == 3
    chunks = await chunks_for(db_session, str(document.id))
    assert [chunk.page_number for chunk in chunks] == [1, 2, 3]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]


@pytest.mark.asyncio
async def test_reference_import_rejects_no_text(db_session: AsyncSession, tmp_path):
    path = await write_pdf(tmp_path, "blank.pdf", " ")
    with pytest.raises(TextExtractionError):
        await import_reference_document(db_session, path, "Blank", EMBEDDING)
    assert await reference_count(db_session) == 0


@pytest.mark.asyncio
async def test_reference_import_rejects_non_pdf(db_session: AsyncSession, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"not a pdf")
    with pytest.raises(Exception):
        await import_reference_document(db_session, path, "Notes", EMBEDDING)
    assert await reference_count(db_session) == 0


@pytest.mark.asyncio
async def test_reference_import_rejects_empty_title(db_session: AsyncSession, tmp_path):
    path = await write_pdf(tmp_path, "doc.pdf", "some text here")
    with pytest.raises(ValueError):
        await import_reference_document(db_session, path, "   ", EMBEDDING)


@pytest.mark.asyncio
async def test_reference_import_duplicate_sha256(db_session: AsyncSession, tmp_path):
    content = "Duplicate reference content REFERENCE-DUP-2026."
    first_path = await write_pdf(tmp_path, "first.pdf", content)
    second_path = await write_pdf(tmp_path, "second.pdf", content)
    first, created_first = await import_reference_document(
        db_session, first_path, "First", EMBEDDING
    )
    second, created_second = await import_reference_document(
        db_session, second_path, "Second", EMBEDDING
    )
    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert await reference_count(db_session) == 1
    assert len(await chunks_for(db_session, str(first.id))) == 1


@pytest.mark.asyncio
async def test_reference_import_embedding_failure_cleanup(db_session: AsyncSession, tmp_path):
    path = await write_pdf(tmp_path, "fail.pdf", "REFERENCE-FAIL-2026 content here.")
    before = await reference_count(db_session)
    with pytest.raises(ProviderError):
        await import_reference_document(db_session, path, "Fail", FailingEmbeddingProvider())
    assert await reference_count(db_session) == before


# ---- Library API ----


@pytest.mark.asyncio
async def test_reference_library_requires_authentication(async_client: AsyncClient):
    response = await async_client.get("/reference-library")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reference_library_lists_metadata(
    async_client: AsyncClient, db_session: AsyncSession, tmp_path
):
    path = await write_pdf(
        tmp_path, "library-guide.pdf", "REFERENCE-LIBRARY-2026 explanatory content."
    )
    document, _ = await import_reference_document(db_session, path, "Library Guide", EMBEDDING)
    token = await register_user(async_client, "library-user@test.com")

    response = await async_client.get("/reference-library", headers=auth_header(token))
    assert response.status_code == 200
    items = response.json()
    assert any(item["id"] == str(document.id) for item in items)
    listed = next(item for item in items if item["id"] == str(document.id))
    assert listed["title"] == "Library Guide"
    assert listed["original_filename"] == "library-guide.pdf"
    assert listed["page_count"] == 1
    assert "embedding" not in listed
    assert "content_sha256" not in listed


@pytest.mark.asyncio
async def test_reference_library_empty_returns_empty_list(async_client: AsyncClient):
    token = await register_user(async_client, "empty-library@test.com")
    response = await async_client.get("/reference-library", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json() == []


# ---- Scope schema ----


@pytest.mark.parametrize("scope", ["private", "reference", "combined"])
@pytest.mark.asyncio
async def test_ask_accepts_valid_scope(async_client: AsyncClient, scope: str):
    token = await register_user(async_client, f"scope-{scope}@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "doc.pdf", "alpha beta gamma")

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "alpha", "knowledge_scope": scope},
        headers=auth_header(token),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ask_omitted_scope_defaults_private(async_client: AsyncClient):
    token = await register_user(async_client, "scope-default@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(async_client, token, space["id"], "doc.pdf", "DEFAULT-SCOPE-2026 alpha")
    ).json()

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "DEFAULT-SCOPE-2026"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["supported"] is True
    assert response.json()["citations"][0]["source_kind"] == "private"
    assert response.json()["citations"][0]["document_id"] == document["id"]
    assert response.json()["citations"][0]["reference_document_id"] is None


@pytest.mark.asyncio
async def test_ask_rejects_arbitrary_scope(async_client: AsyncClient):
    token = await register_user(async_client, "scope-bad@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "doc.pdf", "alpha beta")

    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "alpha", "knowledge_scope": "everything"},
        headers=auth_header(token),
    )
    assert response.status_code == 422


def test_parse_knowledge_scope_defaults():
    assert parse_knowledge_scope(None) == KnowledgeScope.PRIVATE
    assert parse_knowledge_scope("private") == KnowledgeScope.PRIVATE
    assert parse_knowledge_scope("reference") == KnowledgeScope.REFERENCE
    assert parse_knowledge_scope("combined") == KnowledgeScope.COMBINED
    with pytest.raises(ValueError):
        parse_knowledge_scope("bogus")
    with pytest.raises(ValueError):
        parse_knowledge_scope(5)


# ---- Isolation corpus ----


async def setup_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    ref_a_path = await write_pdf(
        tmp_path,
        "insurance-guide.pdf",
        "Shared Insurance Reference REFERENCE-INSURANCE-2026 explains "
        "noticeperiodnoticeness is the time required before cancellation.",
    )
    await import_reference_document(db_session, ref_a_path, "Shared Insurance Reference", EMBEDDING)
    ref_b_path = await write_pdf(
        tmp_path,
        "housing-guide.pdf",
        "Shared Housing Reference HOUSING-SENTINEL-9753 tenancy deposits are protected.",
    )
    await import_reference_document(db_session, ref_b_path, "Shared Housing Reference", EMBEDDING)


@pytest.mark.asyncio
async def test_user_a_private_scope_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token_a = await register_user(async_client, "iso-a@test.com")
    token_b = await register_user(async_client, "iso-b@test.com")
    space_a = await create_space(async_client, token_a, "A")
    space_b = await create_space(async_client, token_b, "B")
    await upload_pdf(
        async_client,
        token_a,
        space_a["id"],
        "a-private.pdf",
        "ALPHA-7319-QUASAR policy requires thirty days notice.",
    )
    await upload_pdf(
        async_client,
        token_b,
        space_b["id"],
        "b-private.pdf",
        "BETA-8421-NEBULA unrelated meeting notes.",
    )

    headers_a = auth_header(token_a)
    own = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "ALPHA-7319-QUASAR", "knowledge_scope": "private"},
        headers=headers_a,
    )
    assert own.json()["supported"] is True
    citation = own.json()["citations"][0]
    assert citation["source_kind"] == "private"
    assert citation["document_name"] == "a-private.pdf"

    other = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "BETA-8421-NEBULA", "knowledge_scope": "private"},
        headers=headers_a,
    )
    assert other.json()["supported"] is False

    reference_leak = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "REFERENCE-INSURANCE-2026", "knowledge_scope": "private"},
        headers=headers_a,
    )
    assert reference_leak.json()["supported"] is False


@pytest.mark.asyncio
async def test_user_a_reference_scope_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token_a = await register_user(async_client, "refiso-a@test.com")
    token_b = await register_user(async_client, "refiso-b@test.com")
    space_a = await create_space(async_client, token_a, "A")
    space_b = await create_space(async_client, token_b, "B")
    await upload_pdf(
        async_client,
        token_a,
        space_a["id"],
        "a-private.pdf",
        "ALPHA-7319-QUASAR policy requires thirty days notice.",
    )
    await upload_pdf(
        async_client,
        token_b,
        space_b["id"],
        "b-private.pdf",
        "BETA-8421-NEBULA unrelated content.",
    )

    headers_a = auth_header(token_a)
    ref = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "REFERENCE-INSURANCE-2026", "knowledge_scope": "reference"},
        headers=headers_a,
    )
    assert ref.json()["supported"] is True
    citation = ref.json()["citations"][0]
    assert citation["source_kind"] == "reference"
    assert citation["document_name"] == "Shared Insurance Reference"
    assert citation["document_id"] is None
    assert citation["reference_document_id"] is not None

    private_in_ref = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "ALPHA-7319-QUASAR", "knowledge_scope": "reference"},
        headers=headers_a,
    )
    assert private_in_ref.json()["supported"] is False

    other_in_ref = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "BETA-8421-NEBULA", "knowledge_scope": "reference"},
        headers=headers_a,
    )
    assert other_in_ref.json()["supported"] is False


@pytest.mark.asyncio
async def test_user_a_combined_scope_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token_a = await register_user(async_client, "combiso-a@test.com")
    token_b = await register_user(async_client, "combiso-b@test.com")
    space_a = await create_space(async_client, token_a, "A")
    space_b = await create_space(async_client, token_b, "B")
    await upload_pdf(
        async_client,
        token_a,
        space_a["id"],
        "a-private.pdf",
        "ALPHA-7319-QUASAR policy noticeperiodnoticeness requires thirty days notice.",
    )
    await upload_pdf(
        async_client,
        token_b,
        space_b["id"],
        "b-private.pdf",
        "BETA-8421-NEBULA unrelated meeting notes.",
    )

    headers_a = auth_header(token_a)
    own = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "ALPHA-7319-QUASAR", "knowledge_scope": "combined"},
        headers=headers_a,
    )
    assert own.json()["supported"] is True

    ref = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "REFERENCE-INSURANCE-2026", "knowledge_scope": "combined"},
        headers=headers_a,
    )
    assert ref.json()["supported"] is True
    assert ref.json()["citations"][0]["source_kind"] == "reference"

    install_answer_provider(CiteAllProvider())
    both = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "noticeperiodnoticeness", "knowledge_scope": "combined"},
        headers=headers_a,
    )
    assert both.json()["supported"] is True
    kinds = {citation["source_kind"] for citation in both.json()["citations"]}
    assert "private" in kinds
    assert "reference" in kinds
    app.dependency_overrides.pop(get_answer_provider, None)

    never_b = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "BETA-8421-NEBULA", "knowledge_scope": "combined"},
        headers=headers_a,
    )
    assert never_b.json()["supported"] is False


@pytest.mark.asyncio
async def test_user_b_symmetric_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token_a = await register_user(async_client, "sym-a@test.com")
    token_b = await register_user(async_client, "sym-b@test.com")
    space_a = await create_space(async_client, token_a, "A")
    space_b = await create_space(async_client, token_b, "B")
    await upload_pdf(
        async_client,
        token_a,
        space_a["id"],
        "a-private.pdf",
        "ALPHA-7319-QUASAR policy requires thirty days notice.",
    )
    await upload_pdf(
        async_client,
        token_b,
        space_b["id"],
        "b-private.pdf",
        "BETA-8421-NEBULA housing deposit information.",
    )

    headers_b = auth_header(token_b)
    own = await async_client.post(
        f"{SPACES_URL}/{space_b['id']}/ask",
        json={"question": "BETA-8421-NEBULA", "knowledge_scope": "private"},
        headers=headers_b,
    )
    assert own.json()["supported"] is True
    assert own.json()["citations"][0]["document_name"] == "b-private.pdf"

    ref = await async_client.post(
        f"{SPACES_URL}/{space_b['id']}/ask",
        json={"question": "HOUSING-SENTINEL-9753", "knowledge_scope": "reference"},
        headers=headers_b,
    )
    assert ref.json()["supported"] is True
    assert ref.json()["citations"][0]["document_name"] == "Shared Housing Reference"

    never_a = await async_client.post(
        f"{SPACES_URL}/{space_b['id']}/ask",
        json={"question": "ALPHA-7319-QUASAR", "knowledge_scope": "combined"},
        headers=headers_b,
    )
    assert never_a.json()["supported"] is False


@pytest.mark.asyncio
async def test_cross_space_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token = await register_user(async_client, "cross-space-ref@test.com")
    space_a1 = await create_space(async_client, token, "A1")
    space_a2 = await create_space(async_client, token, "A2")
    await upload_pdf(
        async_client,
        token,
        space_a1["id"],
        "a1.pdf",
        "QUASAR-A1-9090 private alpha",
    )
    await upload_pdf(
        async_client,
        token,
        space_a2["id"],
        "a2.pdf",
        "NEBULA-A2-1010 private beta",
    )

    headers = auth_header(token)
    wrong_space = await async_client.post(
        f"{SPACES_URL}/{space_a2['id']}/ask",
        json={"question": "QUASAR-A1-9090", "knowledge_scope": "private"},
        headers=headers,
    )
    assert wrong_space.json()["supported"] is False

    combined_wrong_space = await async_client.post(
        f"{SPACES_URL}/{space_a2['id']}/ask",
        json={"question": "QUASAR-A1-9090", "knowledge_scope": "combined"},
        headers=headers,
    )
    assert combined_wrong_space.json()["supported"] is False


# ---- Retrieval service / ranking ----


@pytest.mark.asyncio
async def test_retrieve_chunks_service_scope_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token_a = await register_user(async_client, "svc-a@test.com")
    token_b = await register_user(async_client, "svc-b@test.com")
    space_a = await create_space(async_client, token_a, "A")
    space_b = await create_space(async_client, token_b, "B")
    await upload_pdf(
        async_client,
        token_a,
        space_a["id"],
        "a-private.pdf",
        "ALPHA-7319-QUASAR noticeperiodnoticeness policy.",
    )
    await upload_pdf(
        async_client,
        token_b,
        space_b["id"],
        "b-private.pdf",
        "BETA-8421-NEBULA unrelated.",
    )
    user_row = (
        await db_session.execute(
            select(KnowledgeSpace).where(KnowledgeSpace.id == uuid.UUID(space_a["id"]))
        )
    ).scalar_one()
    user_id = user_row.user_id

    private = await retrieve_chunks(
        db_session,
        uuid.UUID(space_a["id"]),
        user_id,
        "ALPHA-7319-QUASAR",
        5,
        EMBEDDING,
        KnowledgeScope.PRIVATE,
    )
    assert len(private) == 1
    assert private[0].source_kind == "private"
    assert private[0].document_name == "a-private.pdf"

    reference = await retrieve_chunks(
        db_session,
        uuid.UUID(space_a["id"]),
        user_id,
        "REFERENCE-INSURANCE-2026",
        5,
        EMBEDDING,
        KnowledgeScope.REFERENCE,
    )
    assert len(reference) == 1
    assert reference[0].source_kind == "reference"
    assert reference[0].source_id.startswith("reference:")

    combined = await retrieve_chunks(
        db_session,
        uuid.UUID(space_a["id"]),
        user_id,
        "noticeperiodnoticeness",
        5,
        EMBEDDING,
        KnowledgeScope.COMBINED,
    )
    kinds = {candidate.source_kind for candidate in combined}
    assert "private" in kinds
    assert "reference" in kinds
    assert not any(
        candidate.source_kind == "private" and candidate.document_name == "b-private.pdf"
        for candidate in combined
    )


@pytest.mark.asyncio
async def test_combined_top_k_is_global(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token = await register_user(async_client, "topk-global@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(
        async_client,
        token,
        space["id"],
        "a-private.pdf",
        "ALPHA-7319-QUASAR policy noticeperiodnoticeness requires thirty days notice.",
    )
    user_row = (
        await db_session.execute(
            select(KnowledgeSpace).where(KnowledgeSpace.id == uuid.UUID(space["id"]))
        )
    ).scalar_one()

    combined = await retrieve_chunks(
        db_session,
        uuid.UUID(space["id"]),
        user_row.user_id,
        "noticeperiodnoticeness",
        1,
        EMBEDDING,
        KnowledgeScope.COMBINED,
    )
    assert len(combined) == 1


@pytest.mark.asyncio
async def test_reference_not_ready_is_excluded(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    path = await write_pdf(
        tmp_path, "pending-ref.pdf", "PENDING-REF-2026 explanatory content here."
    )
    document, _ = await import_reference_document(db_session, path, "Pending Ref", EMBEDDING)
    document.status = "failed"
    await db_session.commit()

    token = await register_user(async_client, "notready@test.com")
    space = await create_space(async_client, token)
    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "PENDING-REF-2026", "knowledge_scope": "reference"},
        headers=auth_header(token),
    )
    assert response.json()["supported"] is False


# ---- Citation validation / spoofing ----


@pytest.mark.asyncio
async def test_citation_unknown_source_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    token = await register_user(async_client, "cit-unknown@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(
        async_client,
        token,
        space["id"],
        "doc.pdf",
        "ALPHA-7319-QUASAR noticeperiodnoticeness policy text.",
    )
    install_answer_provider(SpoofAnswerProvider([f"private:{uuid.uuid4()}"]))
    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "ALPHA-7319-QUASAR"},
        headers=auth_header(token),
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_citation_prefix_swap_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token = await register_user(async_client, "cit-prefix@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(
        async_client,
        token,
        space["id"],
        "doc.pdf",
        "ALPHA-7319-QUASAR noticeperiodnoticeness policy text.",
    )
    private_chunk_id = await db_session.scalar(select(ReferenceDocumentChunk.id).limit(1))
    install_answer_provider(SpoofAnswerProvider([f"reference:{private_chunk_id}"]))
    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "ALPHA-7319-QUASAR", "knowledge_scope": "combined"},
        headers=auth_header(token),
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_citation_db_valid_but_not_in_context_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token = await register_user(async_client, "cit-context@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(
        async_client,
        token,
        space["id"],
        "doc.pdf",
        "ALPHA-7319-QUASAR noticeperiodnoticeness policy text.",
    )
    reference_ids = list((await db_session.execute(select(ReferenceDocumentChunk.id))).scalars())
    assert len(reference_ids) >= 2
    context_chunk = str(reference_ids[0])
    install_answer_provider(
        SpoofAnswerProvider(
            [
                f"private:{context_chunk}",  # exists in DB as reference chunk, cited as private
            ]
        )
    )
    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "ALPHA-7319-QUASAR", "knowledge_scope": "combined"},
        headers=auth_header(token),
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_citation_another_users_private_chunk_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    token_a = await register_user(async_client, "spoof-a@test.com")
    token_b = await register_user(async_client, "spoof-b@test.com")
    space_a = await create_space(async_client, token_a)
    space_b = await create_space(async_client, token_b)
    await upload_pdf(
        async_client,
        token_a,
        space_a["id"],
        "a.pdf",
        "ALPHA-7319-QUASAR noticeperiodnoticeness policy text.",
    )
    await upload_pdf(async_client, token_b, space_b["id"], "b.pdf", "BETA-8421-NEBULA other text")
    b_document = (
        await db_session.execute(select(Document).where(Document.original_filename == "b.pdf"))
    ).scalar_one()
    b_chunk = (
        await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == b_document.id)
        )
    ).scalar_one()
    install_answer_provider(SpoofAnswerProvider([f"private:{b_chunk.id}"]))
    response = await async_client.post(
        f"{SPACES_URL}/{space_a['id']}/ask",
        json={"question": "ALPHA-7319-QUASAR", "knowledge_scope": "combined"},
        headers=auth_header(token_a),
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_citation_source_kind_is_server_derived(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
):
    await setup_isolation(async_client, db_session, tmp_path)
    token = await register_user(async_client, "kind@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(
        async_client,
        token,
        space["id"],
        "doc.pdf",
        "ALPHA-7319-QUASAR noticeperiodnoticeness policy text.",
    )
    response = await async_client.post(
        f"{SPACES_URL}/{space['id']}/ask",
        json={"question": "noticeperiodnoticeness", "knowledge_scope": "combined"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["supported"] is True
    for citation in response.json()["citations"]:
        assert citation["source_kind"] in {"private", "reference"}
