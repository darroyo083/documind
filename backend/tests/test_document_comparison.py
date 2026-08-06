import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.comparisons import comparison_signature
from app.application.dependencies import get_comparison_provider
from app.config import settings
from app.domain.comparison import (
    DocumentComparisonContext,
    ProviderCommonality,
    ProviderComparisonDimension,
    ProviderComparisonFinding,
    ProviderComparisonResult,
    ProviderKeyDifference,
    document_ref,
)
from app.domain.errors import ProviderError
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    DocumentComparison,
    DocumentComparisonDocument,
    DocumentStatus,
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


async def create_space(client: AsyncClient, token: str, name: str = "Comparison") -> dict:
    response = await client.post(SPACES_URL, json={"name": name}, headers=auth_header(token))
    assert response.status_code == 201
    return response.json()


async def upload_pdf(
    client: AsyncClient,
    token: str,
    space_id: str,
    text: str,
    filename: str = "fixture.pdf",
):
    bytes_data = text_pdf(text)
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": (filename, bytes_data, "application/pdf")},
    )


def comparisons_path(space_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/comparisons"


def comparison_path(space_id: str, comparison_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/comparisons/{comparison_id}"


def default_provider_result(context: DocumentComparisonContext) -> ProviderComparisonResult:
    findings = []
    for document in context.documents:
        source_id = document.sources[0].source_id
        findings.append(
            ProviderComparisonFinding(
                document_ref=document_ref(document.position),
                value="30 days",
                not_identified=False,
                source_ids=[source_id],
            )
        )
    dimension = ProviderComparisonDimension(
        label="Termination notice",
        findings=findings,
        synthesis="The selected documents state the same value.",
        source_ids=[finding.source_ids[0] for finding in findings],
    )
    return ProviderComparisonResult(
        title="Fixture Comparison",
        summary="A fixture comparison of the selected documents.",
        dimensions=[dimension],
        key_differences=[],
        commonalities=[],
    )


class StubComparisonProvider:
    model_name = "stub-comparison"

    def __init__(self, result=None, exception=None, result_fn=None):
        self.calls = 0
        self.context = None
        self.result = result
        self.exception = exception
        self.result_fn = result_fn

    async def compare(self, context: DocumentComparisonContext) -> ProviderComparisonResult:
        self.calls += 1
        self.context = context
        if self.exception is not None:
            raise self.exception
        if self.result_fn is not None:
            return await self.result_fn(context)
        return self.result if self.result is not None else default_provider_result(context)


def install_provider(stub: StubComparisonProvider) -> None:
    app.dependency_overrides[get_comparison_provider] = lambda: stub


def dimension(
    label: str,
    context: DocumentComparisonContext,
    *,
    values: list[str | None] | None = None,
    not_identified: list[bool] | None = None,
    source_ids: list[list[str]] | None = None,
) -> ProviderComparisonDimension:
    findings = []
    for index, document in enumerate(context.documents):
        identified = not_identified is None or not not_identified[index]
        value = values[index] if values is not None else "stated value"
        sources = source_ids[index] if source_ids is not None else [document.sources[0].source_id]
        findings.append(
            ProviderComparisonFinding(
                document_ref=document_ref(document.position),
                value=value if identified else None,
                not_identified=not identified,
                source_ids=sources if identified else [],
            )
        )
    return ProviderComparisonDimension(
        label=label,
        findings=findings,
        synthesis=None,
        source_ids=[],
    )


@pytest.mark.asyncio
async def test_comparison_success_creates_ready_comparison(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-success@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["title"] == "Fixture Comparison"
    assert payload["summary"].startswith("A fixture comparison")
    assert payload["focus"] is None
    assert len(payload["documents"]) == 2
    assert {member["original_filename"] for member in payload["documents"]} == {
        "fixture.pdf",
        "second.pdf",
    }
    assert payload["documents"][0]["position"] == 0
    assert payload["documents"][1]["position"] == 1
    assert len(payload["dimensions"]) == 1
    dimension_payload = payload["dimensions"][0]
    assert dimension_payload["label"] == "Termination notice"
    assert len(dimension_payload["findings"]) == 2
    finding = dimension_payload["findings"][0]
    assert finding["value"] == "30 days"
    assert finding["not_identified"] is False
    assert len(finding["sources"]) == 1
    citation = finding["sources"][0]
    assert citation["page_number"] == 1
    assert citation["document_id"] == finding["document_id"]
    assert citation["excerpt"] in {"alpha beta", "gamma delta"}
    assert "user_id" not in payload
    assert "processing_attempt_id" not in payload
    assert "processing_started_at" not in payload

    row = await db_session.scalar(
        select(DocumentComparison).where(
            DocumentComparison.knowledge_space_id == uuid.UUID(space["id"])
        )
    )
    assert row is not None
    assert row.status == "ready"
    assert row.processing_attempt_id is None
    assert row.processing_started_at is None
    assert row.comparison_signature == comparison_signature(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], None
    )


@pytest.mark.asyncio
async def test_comparison_members_and_json_are_persisted(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-persist@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 201
    comparison_id = response.json()["id"]

    members = (
        await db_session.scalars(
            select(DocumentComparisonDocument)
            .where(DocumentComparisonDocument.comparison_id == uuid.UUID(comparison_id))
            .order_by(DocumentComparisonDocument.position)
        )
    ).all()
    expected_members = sorted(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])],
        key=str,
    )
    assert [member.document_id for member in members] == expected_members
    assert [member.position for member in members] == [0, 1]
    row = await db_session.scalar(
        select(DocumentComparison).where(DocumentComparison.id == uuid.UUID(comparison_id))
    )
    assert row is not None
    assert row.comparison_dimensions[0]["label"] == "Termination notice"
    assert row.key_differences == []
    assert row.commonalities == []
    assert row.error_message is None

    fetched = await async_client.get(
        comparison_path(space["id"], comparison_id), headers=auth_header(token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == comparison_id
    assert fetched.json()["dimensions"] == response.json()["dimensions"]


@pytest.mark.asyncio
async def test_request_validation_errors(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-validation@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    document_c = (await upload_pdf(async_client, token, space["id"], "epsilon zeta")).json()

    single = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"]]},
    )
    assert single.status_code == 422

    five = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={
            "document_ids": [
                document_a["id"],
                document_b["id"],
                document_c["id"],
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            ]
        },
    )
    assert five.status_code == 422

    duplicates = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_a["id"]]},
    )
    assert duplicates.status_code == 422
    assert "unique" in duplicates.json()["detail"]

    long_focus = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={
            "document_ids": [document_a["id"], document_b["id"]],
            "focus": "x" * (settings.comparison_max_focus_length + 1),
        },
    )
    assert long_focus.status_code == 422

    extra_field = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={
            "document_ids": [document_a["id"], document_b["id"]],
            "provider": "deepseek",
        },
    )
    assert extra_field.status_code == 422


@pytest.mark.asyncio
async def test_empty_document_ids_rejected_by_schema(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-empty@test.com")
    space = await create_space(async_client, token)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": []},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_non_ready_documents_are_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-notready@test.com")
    space = await create_space(async_client, token)
    ready = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    processing = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="processing.pdf",
        storage_key="processing-comparison.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.PROCESSING.value,
    )
    db_session.add(processing)
    await db_session.commit()
    await db_session.refresh(processing)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [ready["id"], str(processing.id)]},
    )
    assert response.status_code == 422
    assert "ready" in response.json()["detail"]

    failed = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="failed.pdf",
        storage_key="failed-comparison.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.FAILED.value,
        error_message="boom",
    )
    db_session.add(failed)
    await db_session.commit()
    await db_session.refresh(failed)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [ready["id"], str(failed.id)]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ready_document_without_chunks_is_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-nochunks@test.com")
    space = await create_space(async_client, token)
    empty = Document(
        knowledge_space_id=uuid.UUID(space["id"]),
        original_filename="empty.pdf",
        storage_key="empty-comparison.pdf",
        media_type="application/pdf",
        file_size=1,
        status=DocumentStatus.READY.value,
        page_count=1,
    )
    db_session.add(empty)
    await db_session.commit()
    await db_session.refresh(empty)
    other = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [str(empty.id), other["id"]]},
    )
    assert response.status_code == 422
    assert "no chunks" in response.json()["detail"]


@pytest.mark.asyncio
async def test_context_too_large_is_rejected_before_provider_call(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(settings, "comparison_max_context_chars", 50)
    token = await register_user(async_client, "cmp-toolarge@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 422
    assert "context size" in response.json()["detail"]
    assert stub.calls == 0
    count = await db_session.scalar(
        select(func.count())
        .select_from(DocumentComparison)
        .where(DocumentComparison.knowledge_space_id == uuid.UUID(space["id"]))
    )
    assert count == 0


@pytest.mark.asyncio
async def test_cross_user_document_returns_404(async_client: AsyncClient):
    owner_token = await register_user(async_client, "cmp-owner@test.com")
    intruder_token = await register_user(async_client, "cmp-intruder@test.com")
    owner_space = await create_space(async_client, owner_token)
    intruder_space = await create_space(async_client, intruder_token, "Intruder")
    owner_doc = (
        await upload_pdf(async_client, owner_token, owner_space["id"], "alpha beta")
    ).json()
    intruder_doc = (
        await upload_pdf(async_client, intruder_token, intruder_space["id"], "gamma delta")
    ).json()

    mixed = await async_client.post(
        comparisons_path(owner_space["id"]),
        headers=auth_header(owner_token),
        json={"document_ids": [owner_doc["id"], intruder_doc["id"]]},
    )
    assert mixed.status_code == 404

    foreign_only = await async_client.post(
        comparisons_path(owner_space["id"]),
        headers=auth_header(owner_token),
        json={"document_ids": [intruder_doc["id"], str(uuid.uuid4())]},
    )
    assert foreign_only.status_code == 404

    unknown = await async_client.post(
        comparisons_path(owner_space["id"]),
        headers=auth_header(owner_token),
        json={"document_ids": [str(uuid.uuid4()), str(uuid.uuid4())]},
    )
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_cross_space_same_user_returns_404(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-xspace@test.com")
    space_a = await create_space(async_client, token, "Space A")
    space_b = await create_space(async_client, token, "Space B")
    doc_a = (await upload_pdf(async_client, token, space_a["id"], "alpha beta")).json()
    doc_b = (await upload_pdf(async_client, token, space_b["id"], "gamma delta")).json()

    response = await async_client.post(
        comparisons_path(space_a["id"]),
        headers=auth_header(token),
        json={"document_ids": [doc_a["id"], doc_b["id"]]},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_context_contains_only_selected_documents(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-context@test.com")
    space = await create_space(async_client, token)
    document_a = (
        await upload_pdf(async_client, token, space["id"], "alpha beta", "alpha-doc.pdf")
    ).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "beta-doc.pdf")
    ).json()
    await upload_pdf(async_client, token, space["id"], "SECRET UNRELATED CONTENT", "gamma-doc.pdf")
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 201
    assert stub.calls == 1
    rendered = stub.context.render()
    assert "alpha beta" in rendered
    assert "gamma delta" in rendered
    assert "SECRET UNRELATED CONTENT" not in rendered
    assert {document.document_id for document in stub.context.documents} == {
        uuid.UUID(document_a["id"]),
        uuid.UUID(document_b["id"]),
    }
    assert len(stub.context.documents) == 2
    assert stub.context.focus is None


@pytest.mark.asyncio
async def test_context_contains_focus_and_document_labels(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-focus@test.com")
    space = await create_space(async_client, token)
    document_a = (
        await upload_pdf(async_client, token, space["id"], "alpha beta", "alpha-doc.pdf")
    ).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "beta-doc.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "renewal"},
    )
    assert response.status_code == 201
    assert stub.context.focus == "renewal"
    rendered = stub.context.render()
    assert "COMPARISON FOCUS renewal" in rendered
    assert "DOCUMENT document_1" in rendered
    assert "DOCUMENT document_2" in rendered
    assert "TITLE alpha-doc.pdf" in rendered
    assert "TITLE beta-doc.pdf" in rendered


@pytest.mark.asyncio
async def test_context_chunks_ordered_by_page_then_index(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-order@test.com")
    space = await create_space(async_client, token)
    document = (
        await upload_pdf(async_client, token, space["id"], "alpha beta", "alpha-doc.pdf")
    ).json()
    other = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "beta-doc.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document["id"], other["id"]]},
    )
    assert response.status_code == 201
    for document_context in stub.context.documents:
        pages = [source.page_number for source in document_context.sources]
        assert pages == sorted(pages)


@pytest.mark.asyncio
async def test_ready_idempotency_order_independent(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-idem@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    first = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert first.status_code == 201
    second = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_b["id"], document_a["id"]]},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["documents"][0]["position"] == 0
    assert second.json()["documents"][1]["position"] == 1
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_focus_normalization_affects_identity(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-focusnorm@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    no_focus = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert no_focus.status_code == 201

    whitespace_focus = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "   "},
    )
    assert whitespace_focus.status_code == 200
    assert whitespace_focus.json()["id"] == no_focus.json()["id"]
    assert whitespace_focus.json()["focus"] is None

    padded_focus = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "  renewal  "},
    )
    assert padded_focus.status_code == 201
    assert padded_focus.json()["focus"] == "renewal"

    collapsed_focus = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "renewal   terms"},
    )
    assert collapsed_focus.status_code == 201
    assert collapsed_focus.json()["focus"] == "renewal terms"

    same_collapsed = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "  renewal    terms "},
    )
    assert same_collapsed.status_code == 200
    assert same_collapsed.json()["id"] == collapsed_focus.json()["id"]

    unicode_focus = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "renovación"},
    )
    assert unicode_focus.status_code == 201
    assert unicode_focus.json()["focus"] == "renovación"

    assert stub.calls == 4


@pytest.mark.asyncio
async def test_different_focus_is_distinct_comparison(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-diff-focus@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    general = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    focused = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "renewal"},
    )
    assert general.status_code == 201
    assert focused.status_code == 201
    assert general.json()["id"] != focused.json()["id"]
    assert stub.calls == 2


@pytest.mark.asyncio
async def test_four_document_comparison(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-four@test.com")
    space = await create_space(async_client, token)
    document_ids = []
    for name in ("one", "two", "three", "four"):
        document = (
            await upload_pdf(
                async_client, token, space["id"], f"contents {name}", f"{name}-doc.pdf"
            )
        ).json()
        document_ids.append(document["id"])
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": document_ids},
    )
    assert response.status_code == 201
    payload = response.json()
    assert len(payload["documents"]) == 4
    assert len(payload["dimensions"][0]["findings"]) == 4
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_fresh_processing_returns_conflict(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-fresh@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    signature = comparison_signature(
        [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], None
    )
    old_attempt = uuid.uuid4()
    db_session.add(
        DocumentComparison(
            knowledge_space_id=uuid.UUID(space["id"]),
            status="processing",
            comparison_signature=signature,
            provider="mock",
            processing_started_at=datetime.now(UTC),
            processing_attempt_id=old_attempt,
        )
    )
    await db_session.commit()
    stub = StubComparisonProvider()
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 409
    assert stub.calls == 0
    row = await db_session.scalar(
        select(DocumentComparison).where(
            DocumentComparison.knowledge_space_id == uuid.UUID(space["id"])
        )
    )
    assert row is not None
    assert row.status == "processing"
    assert row.processing_attempt_id == old_attempt


@pytest.mark.asyncio
async def test_failed_comparison_can_be_retried_without_new_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-retry@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    failing = StubComparisonProvider(exception=ProviderError("temporary outage"))
    install_provider(failing)
    first = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert first.status_code == 502
    row = await db_session.scalar(
        select(DocumentComparison).where(
            DocumentComparison.knowledge_space_id == uuid.UUID(space["id"])
        )
    )
    assert row is not None
    assert row.status == "failed"
    assert row.error_message == "temporary outage"
    assert row.comparison_dimensions == []

    succeeding = StubComparisonProvider()
    install_provider(succeeding)
    retry = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "ready"
    assert retry.json()["id"] == str(row.id)
    rows = (
        await db_session.scalars(
            select(DocumentComparison).where(
                DocumentComparison.knowledge_space_id == uuid.UUID(space["id"])
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].error_message is None
    assert rows[0].title == "Fixture Comparison"


@pytest.mark.asyncio
async def test_provider_failure_marks_row_failed_and_returns_502(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-provfail@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider(exception=ProviderError("temporary outage"))
    install_provider(stub)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    row = await db_session.scalar(
        select(DocumentComparison).where(
            DocumentComparison.knowledge_space_id == uuid.UUID(space["id"])
        )
    )
    assert row is not None
    assert row.status == "failed"
    assert row.error_message == "temporary outage"
    assert row.processing_started_at is None
    assert row.processing_attempt_id is None


@pytest.mark.asyncio
async def test_invalid_provider_output_returns_502_and_fails_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-invalid@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def bad_result(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=result.dimensions,
            key_differences=[
                ProviderKeyDifference(
                    title="A difference",
                    description="Only one document is cited.",
                    source_ids=[context.documents[0].sources[0].source_id],
                )
            ],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=bad_result)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    row = await db_session.scalar(
        select(DocumentComparison).where(
            DocumentComparison.knowledge_space_id == uuid.UUID(space["id"])
        )
    )
    assert row is not None
    assert row.status == "failed"
    assert row.error_message is not None
    assert "at least two documents" in row.error_message


@pytest.mark.asyncio
async def test_unknown_source_rejected(async_client: AsyncClient, db_session: AsyncSession):
    token = await register_user(async_client, "cmp-unknown-src@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def bad_source(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=finding.document_ref,
                            value=finding.value,
                            not_identified=False,
                            source_ids=["chunk:not-a-real-uuid"],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=bad_source)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "unknown or unauthorized source" in response.json()["detail"]


@pytest.mark.asyncio
async def test_malformed_source_prefix_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-badprefix@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def bad_prefix(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=finding.document_ref,
                            value=finding.value,
                            not_identified=False,
                            source_ids=["private:spoiled"],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=bad_prefix)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_unselected_same_space_source_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-unselected-src@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    document_c = (
        await upload_pdf(async_client, token, space["id"], "epsilon zeta", "third.pdf")
    ).json()
    chunk_c = await db_session.scalar(
        select(DocumentChunk).where(DocumentChunk.document_id == uuid.UUID(document_c["id"]))
    )
    assert chunk_c is not None
    source_c = f"chunk:{chunk_c.id}"

    async def cross_source(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=finding.document_ref,
                            value=finding.value,
                            not_identified=False,
                            source_ids=[source_c],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=cross_source)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "unknown or unauthorized source" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cross_user_source_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    owner_token = await register_user(async_client, "cmp-xuser-src@test.com")
    intruder_token = await register_user(async_client, "cmp-xuser-src-intruder@test.com")
    owner_space = await create_space(async_client, owner_token)
    intruder_space = await create_space(async_client, intruder_token, "Intruder")
    document_a = (
        await upload_pdf(async_client, owner_token, owner_space["id"], "alpha beta")
    ).json()
    document_b = (
        await upload_pdf(async_client, owner_token, owner_space["id"], "gamma delta", "second.pdf")
    ).json()
    intruder_doc = (
        await upload_pdf(async_client, intruder_token, intruder_space["id"], "epsilon zeta")
    ).json()
    intruder_chunk = await db_session.scalar(
        select(DocumentChunk).where(DocumentChunk.document_id == uuid.UUID(intruder_doc["id"]))
    )
    assert intruder_chunk is not None
    intruder_source = f"chunk:{intruder_chunk.id}"

    async def foreign_source(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=finding.document_ref,
                            value=finding.value,
                            not_identified=False,
                            source_ids=[intruder_source],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=foreign_source)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(owner_space["id"]),
        headers=auth_header(owner_token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "unknown or unauthorized source" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cross_space_source_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-xspace-src@test.com")
    space_a = await create_space(async_client, token, "Space A")
    space_b = await create_space(async_client, token, "Space B")
    document_a = (await upload_pdf(async_client, token, space_a["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space_a["id"], "gamma delta", "second.pdf")
    ).json()
    other_doc = (
        await upload_pdf(async_client, token, space_b["id"], "epsilon zeta", "other-space.pdf")
    ).json()
    other_chunk = await db_session.scalar(
        select(DocumentChunk).where(DocumentChunk.document_id == uuid.UUID(other_doc["id"]))
    )
    assert other_chunk is not None
    other_source = f"chunk:{other_chunk.id}"

    async def other_space_source(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=finding.document_ref,
                            value=finding.value,
                            not_identified=False,
                            source_ids=[other_source],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=other_space_source)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space_a["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "unknown or unauthorized source" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reference_source_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-ref-src@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def reference_source(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=finding.document_ref,
                            value=finding.value,
                            not_identified=False,
                            source_ids=[f"reference:{uuid.uuid4()}"],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=reference_source)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_wrong_document_source_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-wrongdoc-src@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def wrong_doc(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        first = result.dimensions[0].findings[0]
        second = result.dimensions[0].findings[1]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=first.document_ref,
                            value=first.value,
                            not_identified=False,
                            source_ids=second.source_ids,
                        ),
                        ProviderComparisonFinding(
                            document_ref=second.document_ref,
                            value=second.value,
                            not_identified=False,
                            source_ids=second.source_ids,
                        ),
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=wrong_doc)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "its own document" in response.json()["detail"]


@pytest.mark.asyncio
async def test_missing_evidence_for_substantive_finding_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-noevidence@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def no_evidence(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=finding.document_ref,
                            value=finding.value,
                            not_identified=False,
                            source_ids=[],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=no_evidence)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "no supporting evidence" in response.json()["detail"]


@pytest.mark.asyncio
async def test_not_identified_finding_with_sources_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-notid-src@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def not_identified_with_sources(
        context: DocumentComparisonContext,
    ) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=finding.document_ref,
                            value=None,
                            not_identified=True,
                            source_ids=[finding.source_ids[0]],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=not_identified_with_sources)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "must not cite sources" in response.json()["detail"]


@pytest.mark.asyncio
async def test_dimension_must_cover_every_selected_document(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-cover@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def missing_finding(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=result.dimensions[0].findings[:1],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=missing_finding)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "exactly one finding per selected document" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_document_ref_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-badref@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def bad_ref(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        finding = result.dimensions[0].findings[0]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label=result.dimensions[0].label,
                    findings=[
                        ProviderComparisonFinding(
                            document_ref=str(uuid.uuid4()),
                            value=finding.value,
                            not_identified=False,
                            source_ids=[finding.source_ids[0]],
                        ),
                        *result.dimensions[0].findings[1:],
                    ],
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=bad_ref)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "unknown document" in response.json()["detail"]


@pytest.mark.asyncio
async def test_too_many_dimensions_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-manydims@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def many_dimensions(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[result.dimensions[0]] * 9,
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=many_dimensions)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert "dimensions" in response.json()["detail"]


@pytest.mark.asyncio
async def test_too_many_differences_and_commonalities_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-manyitems@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    sources_a = None
    sources_b = None

    async def many_items(context: DocumentComparisonContext) -> ProviderComparisonResult:
        nonlocal sources_a, sources_b
        sources_a = context.documents[0].sources[0].source_id
        sources_b = context.documents[1].sources[0].source_id
        result = default_provider_result(context)
        items = [
            ProviderKeyDifference(
                title=f"Difference {index}",
                description="A difference between the documents.",
                source_ids=[sources_a, sources_b],
            )
            for index in range(7)
        ]
        commonalities = [
            ProviderCommonality(
                title=f"Commonality {index}",
                description="A shared aspect.",
                source_ids=[sources_a, sources_b],
            )
            for index in range(7)
        ]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=result.dimensions,
            key_differences=items,
            commonalities=commonalities,
        )

    stub = StubComparisonProvider(result_fn=many_items)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert (
        "key differences" in response.json()["detail"]
        or "commonalities" in response.json()["detail"]
    )


@pytest.mark.asyncio
async def test_valid_differences_and_commonalities_are_persisted(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-diffcom@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def with_items(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        source_a = context.documents[0].sources[0].source_id
        source_b = context.documents[1].sources[0].source_id
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=result.dimensions,
            key_differences=[
                ProviderKeyDifference(
                    title="Notice period differs",
                    description="Document A requires 30 days; document B requires 60 days.",
                    source_ids=[source_a, source_b],
                )
            ],
            commonalities=[
                ProviderCommonality(
                    title="Both require written notice",
                    description="Both documents require written notice.",
                    source_ids=[source_a, source_b],
                )
            ],
        )

    stub = StubComparisonProvider(result_fn=with_items)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["key_differences"][0]["title"] == "Notice period differs"
    assert len(payload["key_differences"][0]["sources"]) == 2
    assert payload["commonalities"][0]["title"] == "Both require written notice"
    assert len(payload["commonalities"][0]["sources"]) == 2


@pytest.mark.asyncio
async def test_list_comparisons_newest_first_and_lightweight(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-list@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    first = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    second = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={
            "document_ids": [document_a["id"], document_b["id"]],
            "focus": "renewal",
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201

    listing = await async_client.get(comparisons_path(space["id"]), headers=auth_header(token))
    assert listing.status_code == 200
    items = listing.json()
    assert [item["id"] for item in items] == [second.json()["id"], first.json()["id"]]
    item = items[0]
    assert set(item) == {
        "id",
        "status",
        "focus",
        "title",
        "documents",
        "created_at",
        "updated_at",
    }
    assert item["status"] == "ready"
    assert item["focus"] == "renewal"
    assert len(item["documents"]) == 2
    assert "dimensions" not in item


@pytest.mark.asyncio
async def test_list_includes_failed_and_processing(
    async_client: AsyncClient, db_session: AsyncSession
):
    token = await register_user(async_client, "cmp-liststates@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    failing = StubComparisonProvider(exception=ProviderError("temporary outage"))
    install_provider(failing)
    failed = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert failed.status_code == 502
    db_session.add(
        DocumentComparison(
            knowledge_space_id=uuid.UUID(space["id"]),
            status="processing",
            comparison_signature=comparison_signature(
                [uuid.UUID(document_a["id"]), uuid.UUID(document_b["id"])], "in progress"
            ),
            focus="in progress",
            provider="mock",
            processing_started_at=datetime.now(UTC),
            processing_attempt_id=uuid.uuid4(),
        )
    )
    await db_session.commit()

    listing = await async_client.get(comparisons_path(space["id"]), headers=auth_header(token))
    assert listing.status_code == 200
    items = listing.json()
    assert {item["status"] for item in items} == {"failed", "processing"}


@pytest.mark.asyncio
async def test_detail_returns_full_structure_and_is_space_scoped(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-detail@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)
    created = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "terms"},
    )
    assert created.status_code == 201
    comparison_id = created.json()["id"]

    fetched = await async_client.get(
        comparison_path(space["id"], comparison_id), headers=auth_header(token)
    )
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["focus"] == "terms"
    assert payload["provider"] == "mock"
    assert payload["model"] == "stub-comparison"
    assert payload["error_message"] is None

    not_found = await async_client.get(
        comparison_path(space["id"], str(uuid.uuid4())), headers=auth_header(token)
    )
    assert not_found.status_code == 404


@pytest.mark.asyncio
async def test_cross_user_list_and_detail_return_404(async_client: AsyncClient):
    owner_token = await register_user(async_client, "cmp-owner2@test.com")
    intruder_token = await register_user(async_client, "cmp-intruder2@test.com")
    owner_space = await create_space(async_client, owner_token)
    document_a = (
        await upload_pdf(async_client, owner_token, owner_space["id"], "alpha beta")
    ).json()
    document_b = (
        await upload_pdf(async_client, owner_token, owner_space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)
    created = await async_client.post(
        comparisons_path(owner_space["id"]),
        headers=auth_header(owner_token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert created.status_code == 201
    comparison_id = created.json()["id"]

    intruder_space = await create_space(async_client, intruder_token, "Intruder")
    listing = await async_client.get(
        comparisons_path(owner_space["id"]), headers=auth_header(intruder_token)
    )
    assert listing.status_code == 404
    detail = await async_client.get(
        comparison_path(owner_space["id"], comparison_id), headers=auth_header(intruder_token)
    )
    assert detail.status_code == 404
    detail_other_space = await async_client.get(
        comparison_path(intruder_space["id"], comparison_id), headers=auth_header(intruder_token)
    )
    assert detail_other_space.status_code == 404


@pytest.mark.asyncio
async def test_refresh_persistence_without_provider_recall(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-refresh@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    created = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]], "focus": "payment"},
    )
    assert created.status_code == 201
    comparison_id = created.json()["id"]
    assert stub.calls == 1

    listing = await async_client.get(comparisons_path(space["id"]), headers=auth_header(token))
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == comparison_id

    fetched = await async_client.get(
        comparison_path(space["id"], comparison_id), headers=auth_header(token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["dimensions"] == created.json()["dimensions"]
    assert fetched.json()["summary"] == created.json()["summary"]
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_deleting_source_document_removes_dependent_comparisons(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-delete@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()
    document_c = (await upload_pdf(async_client, token, space["id"], "epsilon zeta")).json()
    stub = StubComparisonProvider()
    install_provider(stub)

    ab = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert ab.status_code == 201
    ac = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_c["id"]]},
    )
    assert ac.status_code == 201

    deleted = await async_client.delete(
        f"{SPACES_URL}/{space['id']}/documents/{document_a['id']}",
        headers=auth_header(token),
    )
    assert deleted.status_code == 204

    listing = await async_client.get(comparisons_path(space["id"]), headers=auth_header(token))
    assert listing.status_code == 200
    assert listing.json() == []

    ab_detail = await async_client.get(
        comparison_path(space["id"], ab.json()["id"]), headers=auth_header(token)
    )
    assert ab_detail.status_code == 404
    ac_detail = await async_client.get(
        comparison_path(space["id"], ac.json()["id"]), headers=auth_header(token)
    )
    assert ac_detail.status_code == 404

    rows = (
        await db_session.scalars(
            select(DocumentComparison).where(
                DocumentComparison.knowledge_space_id == uuid.UUID(space["id"])
            )
        )
    ).all()
    assert rows == []
    members = (
        await db_session.scalars(
            select(DocumentComparisonDocument).where(
                DocumentComparisonDocument.comparison_id == uuid.UUID(ab.json()["id"])
            )
        )
    ).all()
    assert members == []


@pytest.mark.asyncio
async def test_deleting_document_without_comparisons_is_unchanged(
    async_client: AsyncClient,
):
    token = await register_user(async_client, "cmp-delete-plain@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    deleted = await async_client.delete(
        f"{SPACES_URL}/{space['id']}/documents/{document_a['id']}",
        headers=auth_header(token),
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_signature_is_deterministic_and_privacy_safe():
    document_a = uuid.uuid4()
    document_b = uuid.uuid4()
    first = comparison_signature([document_a, document_b], None)
    second = comparison_signature([document_b, document_a], None)
    assert first == second
    assert len(first) == 64
    assert comparison_signature([document_a, document_b], "renewal") != first
    assert comparison_signature([document_a, document_b], "  renewal  ") == comparison_signature(
        [document_a, document_b], "renewal"
    )
    assert comparison_signature([document_a, document_b], "  ") == comparison_signature(
        [document_a, document_b], None
    )
    assert "renewal" not in first


def _mutate_result(
    context: DocumentComparisonContext,
    *,
    title: str = "Fixture Comparison",
    summary: str = "A fixture comparison of the selected documents.",
    dimensions: list[ProviderComparisonDimension] | None = None,
    key_differences: list[ProviderKeyDifference] | None = None,
    commonalities: list[ProviderCommonality] | None = None,
) -> ProviderComparisonResult:
    return ProviderComparisonResult(
        title=title,
        summary=summary,
        dimensions=(
            dimensions if dimensions is not None else default_provider_result(context).dimensions
        ),
        key_differences=key_differences if key_differences is not None else [],
        commonalities=commonalities if commonalities is not None else [],
    )


@pytest.mark.asyncio
async def test_valid_not_identified_finding_is_persisted(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-notid-ok@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def with_not_identified(context: DocumentComparisonContext) -> ProviderComparisonResult:
        result = default_provider_result(context)
        findings = [
            ProviderComparisonFinding(
                document_ref=finding.document_ref,
                value=None,
                not_identified=True,
                source_ids=[],
            )
            for finding in result.dimensions[0].findings
        ]
        return ProviderComparisonResult(
            title=result.title,
            summary=result.summary,
            dimensions=[
                ProviderComparisonDimension(
                    label="Cancellation fee",
                    findings=findings,
                    synthesis=None,
                    source_ids=[],
                )
            ],
            key_differences=[],
            commonalities=[],
        )

    stub = StubComparisonProvider(result_fn=with_not_identified)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 201
    payload = response.json()
    dimension = payload["dimensions"][0]
    assert dimension["label"] == "Cancellation fee"
    assert all(finding["not_identified"] is True for finding in dimension["findings"])
    assert all(finding["value"] is None for finding in dimension["findings"])
    assert all(finding["sources"] == [] for finding in dimension["findings"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutator, expected_detail",
    [
        (
            lambda context: None,
            "empty comparison",
        ),
        (
            lambda context: _mutate_result(context, title="   "),
            "comparison title",
        ),
        (
            lambda context: _mutate_result(context, title="x" * 201),
            "title exceeds",
        ),
        (
            lambda context: _mutate_result(context, summary="x" * 2001),
            "Summary exceeds",
        ),
        (
            lambda context: _mutate_result(
                context,
                dimensions=[
                    ProviderComparisonDimension(
                        label="   ",
                        findings=default_provider_result(context).dimensions[0].findings,
                        synthesis=None,
                        source_ids=[],
                    )
                ],
            ),
            "missing a label",
        ),
        (
            lambda context: _mutate_result(
                context,
                dimensions=[
                    ProviderComparisonDimension(
                        label="x" * 201,
                        findings=default_provider_result(context).dimensions[0].findings,
                        synthesis=None,
                        source_ids=[],
                    )
                ],
            ),
            "label exceeds",
        ),
        (
            lambda context: _mutate_result(
                context,
                dimensions=[
                    ProviderComparisonDimension(
                        label="Duplicate findings",
                        findings=default_provider_result(context).dimensions[0].findings
                        + default_provider_result(context).dimensions[0].findings,
                        synthesis=None,
                        source_ids=[],
                    )
                ],
            ),
            "duplicate document findings",
        ),
        (
            lambda context: _mutate_result(
                context,
                dimensions=[
                    ProviderComparisonDimension(
                        label="Empty findings",
                        findings=[],
                        synthesis=None,
                        source_ids=[],
                    )
                ],
            ),
            "exactly one finding per selected document",
        ),
        (
            lambda context: _mutate_result(
                context,
                dimensions=[
                    ProviderComparisonDimension(
                        label="No value",
                        findings=[
                            ProviderComparisonFinding(
                                document_ref=finding.document_ref,
                                value=None,
                                not_identified=False,
                                source_ids=[],
                            )
                            for finding in default_provider_result(context).dimensions[0].findings
                        ],
                        synthesis=None,
                        source_ids=[],
                    )
                ],
            ),
            "missing a value",
        ),
        (
            lambda context: _mutate_result(
                context,
                dimensions=[
                    ProviderComparisonDimension(
                        label="Oversize value",
                        findings=[
                            ProviderComparisonFinding(
                                document_ref=finding.document_ref,
                                value="x" * 1001,
                                not_identified=False,
                                source_ids=finding.source_ids,
                            )
                            for finding in default_provider_result(context).dimensions[0].findings
                        ],
                        synthesis=None,
                        source_ids=[],
                    )
                ],
            ),
            "value exceeds",
        ),
        (
            lambda context: _mutate_result(
                context,
                dimensions=[
                    ProviderComparisonDimension(
                        label="Oversize synthesis",
                        findings=default_provider_result(context).dimensions[0].findings,
                        synthesis="x" * 1001,
                        source_ids=[],
                    )
                ],
            ),
            "synthesis exceeds",
        ),
        (
            lambda context: _mutate_result(
                context,
                key_differences=[
                    ProviderKeyDifference(
                        title="Oversize description",
                        description="x" * 1001,
                        source_ids=[
                            context.documents[0].sources[0].source_id,
                            context.documents[1].sources[0].source_id,
                        ],
                    )
                ],
            ),
            "description exceeds",
        ),
        (
            lambda context: _mutate_result(
                context,
                commonalities=[
                    ProviderCommonality(
                        title="x" * 201,
                        description="Anything",
                        source_ids=[
                            context.documents[0].sources[0].source_id,
                            context.documents[1].sources[0].source_id,
                        ],
                    )
                ],
            ),
            "title exceeds",
        ),
        (
            lambda context: _mutate_result(
                context,
                commonalities=[
                    ProviderCommonality(
                        title="Oversize description",
                        description="x" * 1001,
                        source_ids=[
                            context.documents[0].sources[0].source_id,
                            context.documents[1].sources[0].source_id,
                        ],
                    )
                ],
            ),
            "description exceeds",
        ),
        (
            lambda context: _mutate_result(
                context,
                commonalities=[
                    ProviderCommonality(
                        title="Single document only",
                        description="Anything",
                        source_ids=[context.documents[0].sources[0].source_id],
                    )
                ],
            ),
            "at least two documents",
        ),
        (
            lambda context: _mutate_result(
                context,
                dimensions=[
                    ProviderComparisonDimension(
                        label="Too many sources",
                        findings=[
                            ProviderComparisonFinding(
                                document_ref=finding.document_ref,
                                value=finding.value,
                                not_identified=False,
                                source_ids=[
                                    f"chunk:{uuid.uuid4()}"
                                    for _ in range(settings.comparison_max_sources_per_item + 1)
                                ],
                            )
                            for finding in default_provider_result(context).dimensions[0].findings
                        ],
                        synthesis=None,
                        source_ids=[],
                    )
                ],
            ),
            "more sources than the configured maximum",
        ),
        (
            lambda context: _mutate_result(
                context,
                key_differences=[
                    ProviderKeyDifference(
                        title="   ",
                        description="Anything",
                        source_ids=[context.documents[0].sources[0].source_id],
                    )
                ],
            ),
            "missing a title",
        ),
        (
            lambda context: _mutate_result(
                context,
                key_differences=[
                    ProviderKeyDifference(
                        title="No description",
                        description="   ",
                        source_ids=[context.documents[0].sources[0].source_id],
                    )
                ],
            ),
            "missing a description",
        ),
        (
            lambda context: _mutate_result(
                context,
                key_differences=[
                    ProviderKeyDifference(
                        title="x" * 201,
                        description="Anything",
                        source_ids=[context.documents[0].sources[0].source_id],
                    )
                ],
            ),
            "title exceeds",
        ),
        (
            lambda context: _mutate_result(
                context,
                commonalities=[
                    ProviderCommonality(
                        title="   ",
                        description="Anything",
                        source_ids=[context.documents[0].sources[0].source_id],
                    )
                ],
            ),
            "missing a title",
        ),
        (
            lambda context: _mutate_result(
                context,
                commonalities=[
                    ProviderCommonality(
                        title="No description",
                        description="   ",
                        source_ids=[context.documents[0].sources[0].source_id],
                    )
                ],
            ),
            "missing a description",
        ),
        (
            lambda context: _mutate_result(
                context,
                commonalities=[
                    ProviderCommonality(
                        title="x" * 201,
                        description="Anything",
                        source_ids=[context.documents[0].sources[0].source_id],
                    )
                ]
                * 7,
            ),
            "Too many commonalities",
        ),
    ],
)
async def test_provider_validation_branches(
    async_client: AsyncClient,
    mutator,
    expected_detail: str,
):
    token = await register_user(async_client, f"cmp-branch-{uuid.uuid4().hex[:8]}@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    document_b = (
        await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    ).json()

    async def produce(context: DocumentComparisonContext) -> ProviderComparisonResult | None:
        return mutator(context)

    stub = StubComparisonProvider(result_fn=produce)
    install_provider(stub)
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 502
    assert expected_detail in response.json()["detail"]


@pytest.mark.asyncio
async def test_no_comparison_row_created_for_validation_failures(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    token = await register_user(async_client, "cmp-norow@test.com")
    space = await create_space(async_client, token)
    document_a = (await upload_pdf(async_client, token, space["id"], "alpha beta")).json()
    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"]]},
    )
    assert response.status_code == 422
    count = await db_session.scalar(
        select(func.count())
        .select_from(DocumentComparison)
        .where(DocumentComparison.knowledge_space_id == uuid.UUID(space["id"]))
    )
    assert count == 0


@pytest.mark.asyncio
async def test_deterministic_mock_provider_end_to_end(async_client: AsyncClient):
    token = await register_user(async_client, "cmp-mock@test.com")
    space = await create_space(async_client, token)
    document_a = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            "Service Agreement A. Support window: 8:00 to 18:00. Response target: 4 hours.",
            "service-a.pdf",
        )
    ).json()
    document_b = (
        await upload_pdf(
            async_client,
            token,
            space["id"],
            "Service Agreement B. Support window: 24/7. Response target: 2 hours.",
            "service-b.pdf",
        )
    ).json()
    app.dependency_overrides.pop(get_comparison_provider, None)

    response = await async_client.post(
        comparisons_path(space["id"]),
        headers=auth_header(token),
        json={"document_ids": [document_a["id"], document_b["id"]]},
    )
    assert response.status_code == 201
    payload = response.json()
    assert "service-a.pdf" in payload["title"]
    assert "service-b.pdf" in payload["title"]
    assert payload["provider"] == "mock"
    labels = [dimension["label"] for dimension in payload["dimensions"]]
    assert "Support window" in labels
    assert "Response target" in labels
    support = next(
        dimension for dimension in payload["dimensions"] if dimension["label"] == "Support window"
    )
    values = {finding["value"] for finding in support["findings"]}
    assert values == {"8:00 to 18:00", "24/7"}
    assert any("differs" in difference["title"] for difference in payload["key_differences"])
