import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dependencies import get_analysis_provider
from app.domain.analysis import (
    DocumentAnalysisContext,
    ProviderDocumentAnalysis,
    ProviderImportantDate,
    ProviderKeyFact,
)
from app.domain.errors import ProviderError
from app.infrastructure.models import (
    Document,
    DocumentAnalysis,
    DocumentChunk,
    DocumentStatus,
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


async def create_space(client: AsyncClient, token: str, name: str = "Analysis") -> dict:
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


def analysis_path(space_id: str, document_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/documents/{document_id}/analysis"


def default_provider_result(context: DocumentAnalysisContext) -> ProviderDocumentAnalysis:
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


class StubAnalysisProvider:
    model_name = "stub-analysis"

    def __init__(self, result=None, exception=None, empty=False, result_fn=None):
        self.calls = 0
        self.context = None
        self.result = result
        self.exception = exception
        self.empty = empty
        self.result_fn = result_fn

    async def analyze(self, context: DocumentAnalysisContext) -> ProviderDocumentAnalysis | None:
        self.calls += 1
        self.context = context
        if self.exception is not None:
            raise self.exception
        if self.empty:
            return None
        if self.result_fn is not None:
            return self.result_fn(context)
        return self.result if self.result is not None else default_provider_result(context)


def install_provider(stub: StubAnalysisProvider) -> None:
    app.dependency_overrides[get_analysis_provider] = lambda: stub


async def analysis_rows_for(db_session: AsyncSession, document_id: str) -> list[DocumentAnalysis]:
    result = await db_session.execute(
        select(DocumentAnalysis).where(DocumentAnalysis.document_id == uuid.UUID(document_id))
    )
    return list(result.scalars().all())


async def first_chunk_id(db_session: AsyncSession, document_id: str) -> str:
    chunk_id = await db_session.scalar(
        select(DocumentChunk.id).where(DocumentChunk.document_id == uuid.UUID(document_id))
    )
    assert chunk_id is not None
    return str(chunk_id)


@pytest.mark.asyncio
async def test_analysis_requires_authentication(async_client: AsyncClient):
    response = await async_client.post(analysis_path(str(uuid.uuid4()), str(uuid.uuid4())))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_analysis_requires_authentication(async_client: AsyncClient):
    response = await async_client.get(analysis_path(str(uuid.uuid4()), str(uuid.uuid4())))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_analyses_are_hidden_from_other_users(async_client: AsyncClient):
    owner_token = await register_user(async_client, "analysis-owner@test.com")
    intruder_token = await register_user(async_client, "analysis-intruder@test.com")
    space = await create_space(async_client, owner_token)
    document = (
        await upload_pdf(async_client, owner_token, space["id"], ["alpha beta gamma"])
    ).json()

    path = analysis_path(space["id"], document["id"])
    assert (await async_client.get(path, headers=auth_header(intruder_token))).status_code == 404
    assert (await async_client.post(path, headers=auth_header(intruder_token))).status_code == 404


@pytest.mark.asyncio
async def test_analysis_of_another_space_same_user_returns_404(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-cross-space@test.com")
    space_a = await create_space(async_client, token, "Space A")
    space_b = await create_space(async_client, token, "Space B")
    document = (await upload_pdf(async_client, token, space_a["id"], ["private alpha"])).json()

    response = await async_client.post(
        analysis_path(space_b["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analysis_of_ready_document_succeeds_and_persists(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-ok@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(async_client, token, space["id"], ["alpha beta gamma delta"])
    ).json()
    install_provider(StubAnalysisProvider())

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    analysis = response.json()
    assert analysis["status"] == "ready"
    assert analysis["document_id"] == document["id"]
    assert analysis["document_type"] == "contract"
    assert analysis["normalized_title"] == "Fixture Contract"
    assert analysis["provider"] == "mock"
    assert analysis["model"] == "stub-analysis"
    assert analysis["important_dates"][0]["normalized_date"] == "2026-09-01"
    assert analysis["important_dates"][0]["sources"][0]["page_number"] == 1
    assert analysis["important_dates"][0]["sources"][0]["chunk_id"]
    assert analysis["key_facts"][0]["value"] == "30 days"

    rows = await analysis_rows_for(db_session, document["id"])
    assert len(rows) == 1
    assert rows[0].status == "ready"
    assert rows[0].provider == "mock"
    assert rows[0].model == "stub-analysis"
    assert rows[0].important_dates[0]["normalized_date"] == "2026-09-01"

    fetched = await async_client.get(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == analysis["id"]
    assert fetched.json()["important_dates"] == analysis["important_dates"]
    assert fetched.json()["key_facts"] == analysis["key_facts"]
    assert "document_name" not in fetched.json()
    assert "user_id" not in fetched.json()


@pytest.mark.asyncio
async def test_processing_document_is_rejected(async_client: AsyncClient, db_session: AsyncSession):
    token = await register_user(async_client, "analysis-processing@test.com")
    space = await create_space(async_client, token)
    processing = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="processing.pdf",
        storage_key="processing-analysis.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.PROCESSING.value,
    )
    db_session.add(processing)
    await db_session.commit()
    await db_session.refresh(processing)

    response = await async_client.post(
        analysis_path(space["id"], str(processing.id)), headers=auth_header(token)
    )
    assert response.status_code == 422
    assert "not ready" in response.json()["detail"]


@pytest.mark.asyncio
async def test_failed_document_is_rejected(async_client: AsyncClient, db_session: AsyncSession):
    token = await register_user(async_client, "analysis-failed-doc@test.com")
    space = await create_space(async_client, token)
    failed = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="failed.pdf",
        storage_key="failed-analysis.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.FAILED.value,
        error_message="boom",
    )
    db_session.add(failed)
    await db_session.commit()
    await db_session.refresh(failed)

    response = await async_client.post(
        analysis_path(space["id"], str(failed.id)), headers=auth_header(token)
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ready_document_without_chunks_is_rejected(
    async_client: AsyncClient, db_session: AsyncSession
):
    token = await register_user(async_client, "analysis-nochunks@test.com")
    space = await create_space(async_client, token)
    empty = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="empty.pdf",
        storage_key="empty-analysis.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.READY.value,
        page_count=1,
    )
    db_session.add(empty)
    await db_session.commit()
    await db_session.refresh(empty)

    response = await async_client.post(
        analysis_path(space["id"], str(empty.id)), headers=auth_header(token)
    )
    assert response.status_code == 422
    assert "no chunks" in response.json()["detail"]
    assert await analysis_rows_for(db_session, str(empty.id)) == []


@pytest.mark.asyncio
async def test_processing_analysis_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-conflict@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    db_session.add(
        DocumentAnalysis(
            document_id=uuid.UUID(document["id"]),
            status="processing",
            provider="mock",
            processing_started_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_existing_ready_analysis_is_idempotent(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-idempotent@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    stub = StubAnalysisProvider()
    install_provider(stub)

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
async def test_failed_analysis_can_retry(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-retry@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta gamma"])).json()
    stub = StubAnalysisProvider(exception=ProviderError("temporary outage"))
    install_provider(stub)

    first = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert first.status_code == 502
    rows = await analysis_rows_for(db_session, document["id"])
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error_message == "temporary outage"

    stub.exception = None
    retry = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "ready"
    assert stub.calls == 2


@pytest.mark.asyncio
async def test_invalid_source_id_fails_and_persists_failed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-badsource@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Bad Source",
                summary="This analysis has a bad source.",
                important_dates=[
                    ProviderImportantDate(
                        label="Effective date",
                        value="1 September 2026",
                        normalized_date="2026-09-01",
                        source_ids=["chunk:nonexistent"],
                    )
                ],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    rows = await analysis_rows_for(db_session, document["id"])
    assert rows[0].status == "failed"
    assert rows[0].error_message is not None
    assert "unknown or unauthorized" in rows[0].error_message


@pytest.mark.asyncio
async def test_cross_document_source_reference_is_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-crossdoc@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    other = (await upload_pdf(async_client, token, space["id"], ["other evidence document"])).json()
    foreign_chunk_id = await first_chunk_id(db_session, other["id"])
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Cross Document",
                summary="It references another document.",
                important_dates=[
                    ProviderImportantDate(
                        label="Effective date",
                        value="1 March 2026",
                        normalized_date="2026-03-01",
                        source_ids=[f"chunk:{foreign_chunk_id}"],
                    )
                ],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_analysis_cannot_reference_another_users_chunk(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    other_token = await register_user(async_client, "other-user@test.com")
    token = await register_user(async_client, "current-user@test.com")
    other_space = await create_space(async_client, other_token)
    other_document = (
        await upload_pdf(async_client, other_token, other_space["id"], ["owner data"])
    ).json()
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["my private data"])).json()
    foreign_chunk_id = await first_chunk_id(db_session, other_document["id"])
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Foreign",
                summary="Tries to cite another user's chunk.",
                important_dates=[],
                key_facts=[
                    ProviderKeyFact(
                        label="Coverage",
                        value="broad",
                        source_ids=[f"chunk:{foreign_chunk_id}"],
                    )
                ],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_duplicate_source_ids_are_deduplicated(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-dup@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    real_chunk = await first_chunk_id(db_session, document["id"])
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Dedupe",
                summary="A fact referencing the same source twice.",
                important_dates=[
                    ProviderImportantDate(
                        label="Effective date",
                        value="1 September 2026",
                        normalized_date="2026-09-01",
                        source_ids=["source_1", "source_1"],
                    )
                ],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    sources = response.json()["important_dates"][0]["sources"]
    assert len(sources) == 1
    assert sources[0]["chunk_id"] == real_chunk


@pytest.mark.asyncio
async def test_too_many_sources_per_item_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    from app.config import settings

    token = await register_user(async_client, "analysis-many-sources@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            ["First page content", "Second page content", "Third page content"],
        )
    ).json()
    chunk_ids = list(
        (
            await db_session.execute(
                select(DocumentChunk.id)
                .where(DocumentChunk.document_id == uuid.UUID(document["id"]))
                .order_by(DocumentChunk.page_number)
            )
        ).scalars()
    )
    assert len(chunk_ids) >= 3
    monkeypatch.setattr(settings, "analysis_max_sources_per_item", 2)
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Too Many Sources",
                summary="A date citing more sources than permitted.",
                important_dates=[
                    ProviderImportantDate(
                        label="Effective date",
                        value="1 September 2026",
                        normalized_date="2026-09-01",
                        source_ids=[f"chunk:{chunk}" for chunk in chunk_ids[:3]],
                    )
                ],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "An analysis item references more sources than the configured maximum"
    )
    rows = await analysis_rows_for(db_session, document["id"])
    assert rows[0].status == "failed"


@pytest.mark.asyncio
async def test_missing_sources_for_fact_is_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-nosource@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="No Sources",
                summary="A fact without evidence.",
                important_dates=[],
                key_facts=[
                    ProviderKeyFact(label="Termination notice", value="30 days", source_ids=[])
                ],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_empty_provider_response_is_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-empty@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(StubAnalysisProvider(empty=True))

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Provider returned an empty analysis"


@pytest.mark.asyncio
async def test_source_ids_use_stable_positional_labels(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-stable@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            ["Page one content", "Page two content", "Page three content"],
        )
    ).json()
    stub = StubAnalysisProvider()
    install_provider(stub)

    await async_client.post(analysis_path(space["id"], document["id"]), headers=auth_header(token))
    assert stub.context is not None
    assert [source.source_id for source in stub.context.sources] == [
        "source_1",
        "source_2",
        "source_3",
    ]
    assert stub.context.document_id == uuid.UUID(document["id"])


@pytest.mark.asyncio
async def test_analysis_accepts_missing_title(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-notitle@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="",
                summary="A title-less document.",
                important_dates=[],
                key_facts=[
                    ProviderKeyFact(
                        label="Termination notice",
                        value="30 days",
                        source_ids=["source_1"],
                    )
                ],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert response.json()["normalized_title"] == ""


@pytest.mark.asyncio
async def test_context_orders_sources_by_page_then_chunk(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-order@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            ["Page one content", "Page two content", "Page three content"],
        )
    ).json()
    stub = StubAnalysisProvider()
    install_provider(stub)

    await async_client.post(analysis_path(space["id"], document["id"]), headers=auth_header(token))
    assert stub.context is not None
    pages = [source.page_number for source in stub.context.sources]
    assert pages == sorted(pages)
    assert all("Page" in source.content for source in stub.context.sources)


@pytest.mark.asyncio
async def test_context_contains_only_the_target_document(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-scope@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["TARGET_ONLY_ONE two"])).json()
    (await upload_pdf(async_client, token, space["id"], ["OTHER_DOC_CONTENT three"])).json()

    stub = StubAnalysisProvider()
    install_provider(stub)

    await async_client.post(analysis_path(space["id"], document["id"]), headers=auth_header(token))
    target_chunks = await db_session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == uuid.UUID(document["id"]))
    )
    assert stub.context is not None
    assert len(stub.context.sources) == target_chunks
    assert "OTHER_DOC_CONTENT" not in stub.context.render()


@pytest.mark.asyncio
async def test_context_overflow_is_rejected_not_truncated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    from app.config import settings

    token = await register_user(async_client, "analysis-overflow@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            ["common_name " * 200],
        )
    ).json()
    monkeypatch.setattr(settings, "analysis_max_context_chars", 100)

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 422
    assert "context size" in response.json()["detail"]
    assert await analysis_rows_for(db_session, document["id"]) == []


@pytest.mark.asyncio
async def test_invalid_document_type_is_mapped_to_other(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-type@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="totally_invented_type",
                normalized_title="Mapped",
                summary="Unknown taxonomies map to other.",
                important_dates=[],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert response.json()["document_type"] == "other"


@pytest.mark.asyncio
async def test_unknown_document_type_is_preserved(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-unknown@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="unknown",
                normalized_title="Unknown",
                summary="A general document that does not fit the taxonomy.",
                important_dates=[],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert response.json()["document_type"] == "unknown"


@pytest.mark.asyncio
async def test_too_many_dates_rejected(async_client: AsyncClient, monkeypatch):
    from app.config import settings

    token = await register_user(async_client, "analysis-many-dates@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    monkeypatch.setattr(settings, "analysis_max_important_dates", 1)
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Many Dates",
                summary="A document with too many dates.",
                important_dates=[
                    ProviderImportantDate(
                        label=f"Date {index}",
                        value="1 September 2026",
                        normalized_date="2026-09-01",
                        source_ids=[f"chunk:{uuid.uuid4()}"],
                    )
                    for index in range(3)
                ],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Too many important dates"


@pytest.mark.asyncio
async def test_too_many_facts_rejected(async_client: AsyncClient, monkeypatch):
    from app.config import settings

    token = await register_user(async_client, "analysis-many-facts@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    monkeypatch.setattr(settings, "analysis_max_key_facts", 1)
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Many Facts",
                summary="A document with too many facts.",
                important_dates=[],
                key_facts=[
                    ProviderKeyFact(
                        label=f"Fact {index}",
                        value="value",
                        source_ids=[f"chunk:{uuid.uuid4()}"],
                    )
                    for index in range(3)
                ],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Too many key facts"


@pytest.mark.asyncio
async def test_oversized_summary_rejected(async_client: AsyncClient, monkeypatch):
    from app.config import settings

    token = await register_user(async_client, "analysis-big-summary@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    monkeypatch.setattr(settings, "analysis_max_summary_length", 20)
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Big Summary",
                summary="This summary is far longer than the configured maximum permits.",
                important_dates=[],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Summary exceeds the allowed length"


@pytest.mark.asyncio
async def test_oversized_value_rejected(async_client: AsyncClient, monkeypatch):
    from app.config import settings

    token = await register_user(async_client, "analysis-big-value@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    monkeypatch.setattr(settings, "analysis_max_value_length", 10)
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Big Value",
                summary="A value that is far too long.",
                important_dates=[],
                key_facts=[
                    ProviderKeyFact(
                        label="Termination notice",
                        value="thirty days written notice at the very least",
                        source_ids=[f"chunk:{uuid.uuid4()}"],
                    )
                ],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "A key fact value exceeds the allowed length"


@pytest.mark.asyncio
async def test_invalid_normalized_date_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "analysis-bad-date@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Bad Date",
                summary="A date that cannot be normalized.",
                important_dates=[
                    ProviderImportantDate(
                        label="Effective date",
                        value="1 September 2026",
                        normalized_date="not-a-date",
                        source_ids=[f"chunk:{uuid.uuid4()}"],
                    )
                ],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 502
    assert "not a valid ISO date" in response.json()["detail"]


@pytest.mark.asyncio
async def test_partial_date_stays_null(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-partial@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(
        StubAnalysisProvider(
            result=ProviderDocumentAnalysis(
                document_type="contract",
                normalized_title="Partial Date",
                summary="A date with no day must remain unnormalized.",
                important_dates=[
                    ProviderImportantDate(
                        label="Validity",
                        value="January 2027",
                        normalized_date=None,
                        source_ids=["source_1"],
                    )
                ],
                key_facts=[],
            )
        )
    )

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert response.json()["important_dates"][0]["normalized_date"] is None


@pytest.mark.asyncio
async def test_trusted_citation_uses_stored_page_and_excerpt(
    async_client: AsyncClient,
):
    token = await register_user(async_client, "cite-page@example.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            [
                "Summary paragraph for page one.",
                "Coverage statement for page two.",
                "This policy expires on 31 January 2027.",
            ],
        )
    ).json()

    def scripted(context):
        target = next(s for s in context.sources if "expires on" in s.content)
        return ProviderDocumentAnalysis(
            document_type="insurance_policy",
            normalized_title="Third Page Policy",
            summary="A policy whose expiry appears on the last page.",
            important_dates=[
                ProviderImportantDate(
                    label="Expiration date",
                    value="31 January 2027",
                    normalized_date="2027-01-31",
                    source_ids=[target.source_id],
                )
            ],
            key_facts=[],
        )

    install_provider(StubAnalysisProvider(result_fn=scripted))

    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    date = response.json()["important_dates"][0]
    assert date["normalized_date"] == "2027-01-31"
    assert date["sources"][0]["page_number"] == 3
    assert "expires on 31 January 2027" in date["sources"][0]["excerpt"]
    assert date["sources"][0]["chunk_id"]


@pytest.mark.asyncio
async def test_one_analysis_row_per_document(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-one-row@test.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(StubAnalysisProvider())

    first = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert first.status_code == 201
    second = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert second.status_code == 200
    rows = await analysis_rows_for(db_session, document["id"])
    assert len(rows) == 1
    assert str(rows[0].id) == first.json()["id"]


@pytest.mark.asyncio
async def test_deleting_document_cascades_analysis(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-cascade@example.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(StubAnalysisProvider())
    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert len(await analysis_rows_for(db_session, document["id"])) == 1

    deleted = await async_client.delete(
        f"{SPACES_URL}/{space['id']}/documents/{document['id']}",
        headers=auth_header(token),
    )
    assert deleted.status_code == 204
    assert await analysis_rows_for(db_session, document["id"]) == []


@pytest.mark.asyncio
async def test_deleting_space_cascades_analysis(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "analysis-space-cascade@example.com")
    space = await create_space(async_client, token)
    document = (await upload_pdf(async_client, token, space["id"], ["alpha beta"])).json()
    install_provider(StubAnalysisProvider())
    response = await async_client.post(
        analysis_path(space["id"], document["id"]), headers=auth_header(token)
    )
    assert response.status_code == 201
    assert len(await analysis_rows_for(db_session, document["id"])) == 1

    deleted = await async_client.delete(f"{SPACES_URL}/{space['id']}", headers=auth_header(token))
    assert deleted.status_code == 204
    assert await analysis_rows_for(db_session, document["id"]) == []
    assert await db_session.get(Document, uuid.UUID(document["id"])) is None
