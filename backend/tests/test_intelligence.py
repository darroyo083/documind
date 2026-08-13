import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dependencies import get_intelligence_provider
from app.application.intelligence import space_intelligence_signature
from app.domain.errors import ProviderError
from app.domain.intelligence import (
    ProviderContradiction,
    ProviderDate,
    ProviderKeyFact,
    ProviderOpenQuestion,
    ProviderSpaceIntelligence,
    SpaceIntelligenceContext,
)
from app.infrastructure.models import SpaceIntelligence
from app.main import app
from tests.pdf_factory import text_pdf

SPACES_URL = "/knowledge-spaces"


def intelligence_path(space_id: str) -> str:
    return f"{SPACES_URL}/{space_id}/intelligence"


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


async def create_space(client: AsyncClient, token: str, name: str = "Intelligence") -> dict:
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
    return await client.post(
        f"{SPACES_URL}/{space_id}/documents",
        headers=auth_header(token),
        files={"file": (filename, text_pdf(text), "application/pdf")},
    )


def default_provider_result(context: SpaceIntelligenceContext) -> ProviderSpaceIntelligence:
    first_source = context.documents[0].sources[0]
    second_source = context.documents[1].sources[0] if len(context.documents) > 1 else first_source
    key_facts = [
        ProviderKeyFact(
            title=document.title,
            detail="Membership is billed monthly.",
            source_ids=[document.sources[0].source_id],
        )
        for document in context.documents
    ]
    contradictions = [
        ProviderContradiction(
            topic="Plan duration",
            first_claim="12 months",
            first_source_ids=[first_source.source_id],
            second_claim="18 months",
            second_source_ids=[second_source.source_id],
        )
    ]
    dates = [
        ProviderDate(
            label="Renewal deadline",
            date_text="15 March 2026",
            context="Renewal is due annually.",
            source_ids=[first_source.source_id],
        )
    ]
    open_questions = [
        ProviderOpenQuestion(
            question="What is the cancellation window?",
            explanation="The documents do not state a cancellation window.",
            source_ids=[],
        )
    ]
    return ProviderSpaceIntelligence(
        summary="A fixture intelligence summary across the space documents.",
        key_facts=key_facts,
        contradictions=contradictions,
        dates=dates,
        open_questions=open_questions,
    )


class StubIntelligenceProvider:
    model_name = "stub-intelligence"

    def __init__(self, result=None, exception=None, result_fn=None):
        self.calls = 0
        self.context = None
        self.result = result
        self.exception = exception
        self.result_fn = result_fn

    async def analyze(self, context: SpaceIntelligenceContext) -> ProviderSpaceIntelligence:
        self.calls += 1
        self.context = context
        if self.exception is not None:
            raise self.exception
        if self.result_fn is not None:
            return await self.result_fn(context)
        return self.result if self.result is not None else default_provider_result(context)


def install_provider(stub: StubIntelligenceProvider) -> None:
    app.dependency_overrides[get_intelligence_provider] = lambda: stub


@pytest.mark.asyncio
async def test_owner_can_generate_intelligence(async_client: AsyncClient):
    token = await register_user(async_client, "intel-owner@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")
    await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    stub = StubIntelligenceProvider()
    install_provider(stub)

    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["ready_document_count"] == 2
    assert payload["summary"].startswith("A fixture intelligence summary")
    assert len(payload["key_facts"]) == 2
    assert len(payload["contradictions"]) == 1
    contradiction = payload["contradictions"][0]
    assert contradiction["first_claim"] == "12 months"
    assert contradiction["second_claim"] == "18 months"
    assert len(contradiction["first_sources"]) == 1
    assert len(contradiction["second_sources"]) == 1
    assert len(payload["dates"]) == 1
    assert len(payload["open_questions"]) == 1
    assert "processing_attempt_id" not in payload


@pytest.mark.asyncio
async def test_other_user_cannot_access(async_client: AsyncClient):
    token = await register_user(async_client, "intel-owner2@test.com")
    other = await register_user(async_client, "intel-other@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")

    response = await async_client.get(intelligence_path(space["id"]), headers=auth_header(other))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cross_space_no_leak(async_client: AsyncClient):
    token = await register_user(async_client, "intel-cross@test.com")
    space_a = await create_space(async_client, token, "Space A")
    space_b = await create_space(async_client, token, "Space B")
    await upload_pdf(async_client, token, space_a["id"], "alpha beta")
    await upload_pdf(async_client, token, space_b["id"], "gamma delta")
    install_provider(StubIntelligenceProvider())
    await async_client.post(intelligence_path(space_a["id"]), headers=auth_header(token))

    response = await async_client.get(intelligence_path(space_b["id"]), headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["status"] == "none"
    assert response.json()["ready_document_count"] == 1


@pytest.mark.asyncio
async def test_get_returns_none_when_never_generated(async_client: AsyncClient):
    token = await register_user(async_client, "intel-none@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")

    response = await async_client.get(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "none"
    assert payload["ready_document_count"] == 1
    assert payload["key_facts"] == []


@pytest.mark.asyncio
async def test_no_ready_documents_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "intel-noready@test.com")
    space = await create_space(async_client, token)
    install_provider(StubIntelligenceProvider())

    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_one_document_space_works(async_client: AsyncClient):
    token = await register_user(async_client, "intel-one@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")
    stub = StubIntelligenceProvider()
    install_provider(stub)

    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["ready_document_count"] == 1


@pytest.mark.asyncio
async def test_unknown_source_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "intel-unknownsrc@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")

    async def bad_result(context: SpaceIntelligenceContext) -> ProviderSpaceIntelligence:
        result = default_provider_result(context)
        return replace(
            result,
            key_facts=[replace(result.key_facts[0], source_ids=["chunk:does-not-exist"])],
        )

    install_provider(StubIntelligenceProvider(result_fn=bad_result))
    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_contradiction_requires_both_sides(async_client: AsyncClient):
    token = await register_user(async_client, "intel-contra@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")

    async def bad_result(context: SpaceIntelligenceContext) -> ProviderSpaceIntelligence:
        result = default_provider_result(context)
        return replace(
            result,
            contradictions=[replace(result.contradictions[0], first_source_ids=[])],
        )

    install_provider(StubIntelligenceProvider(result_fn=bad_result))
    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_date_requires_evidence(async_client: AsyncClient):
    token = await register_user(async_client, "intel-date@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")

    async def bad_result(context: SpaceIntelligenceContext) -> ProviderSpaceIntelligence:
        result = default_provider_result(context)
        return replace(result, dates=[replace(result.dates[0], source_ids=[])])

    install_provider(StubIntelligenceProvider(result_fn=bad_result))
    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_empty_categories_allowed(async_client: AsyncClient):
    token = await register_user(async_client, "intel-empty@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")

    async def sparse_result(context: SpaceIntelligenceContext) -> ProviderSpaceIntelligence:
        return ProviderSpaceIntelligence(
            summary="Only a summary.",
            key_facts=[],
            contradictions=[],
            dates=[],
            open_questions=[],
        )

    install_provider(StubIntelligenceProvider(result_fn=sparse_result))
    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["key_facts"] == []
    assert payload["contradictions"] == []


@pytest.mark.asyncio
async def test_malformed_provider_result_rejected(async_client: AsyncClient):
    token = await register_user(async_client, "intel-malformed@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")

    async def none_result(context: SpaceIntelligenceContext) -> None:
        return None

    install_provider(StubIntelligenceProvider(result_fn=none_result))
    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_provider_failure_handled(async_client: AsyncClient, db_session: AsyncSession):
    token = await register_user(async_client, "intel-fail@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")
    install_provider(StubIntelligenceProvider(exception=ProviderError("temporary outage")))

    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 502

    row = await db_session.scalar(
        select(SpaceIntelligence).where(
            SpaceIntelligence.knowledge_space_id == uuid.UUID(space["id"])
        )
    )
    assert row is not None
    assert row.status == "failed"


@pytest.mark.asyncio
async def test_stale_when_document_set_changes(async_client: AsyncClient):
    token = await register_user(async_client, "intel-stale@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")
    install_provider(StubIntelligenceProvider())
    generated = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert generated.json()["is_stale"] is False

    await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    response = await async_client.get(intelligence_path(space["id"]), headers=auth_header(token))
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["is_stale"] is True
    assert payload["ready_document_count"] == 2


@pytest.mark.asyncio
async def test_refresh_updates_snapshot(async_client: AsyncClient):
    token = await register_user(async_client, "intel-refresh@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")
    stub = StubIntelligenceProvider()
    install_provider(stub)
    first = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert first.json()["status"] == "ready"

    await upload_pdf(async_client, token, space["id"], "gamma delta", "second.pdf")
    second = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert second.json()["status"] == "ready"
    assert second.json()["is_stale"] is False
    assert stub.calls == 2


@pytest.mark.asyncio
async def test_idempotent_when_unchanged(async_client: AsyncClient):
    token = await register_user(async_client, "intel-idem@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")
    stub = StubIntelligenceProvider()
    install_provider(stub)
    await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_concurrent_refresh_protected(async_client: AsyncClient, db_session: AsyncSession):
    token = await register_user(async_client, "intel-concurrent@test.com")
    space = await create_space(async_client, token)
    await upload_pdf(async_client, token, space["id"], "alpha beta")
    install_provider(StubIntelligenceProvider())
    await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))

    row = await db_session.scalar(
        select(SpaceIntelligence).where(
            SpaceIntelligence.knowledge_space_id == uuid.UUID(space["id"])
        )
    )
    assert row is not None
    row.status = "processing"
    row.processing_started_at = datetime.now(UTC)
    row.processing_attempt_id = uuid.uuid4()
    await db_session.commit()

    response = await async_client.post(intelligence_path(space["id"]), headers=auth_header(token))
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_signature_deterministic_and_order_independent():
    from types import SimpleNamespace

    updated = datetime(2026, 1, 1, tzinfo=UTC)
    doc_a = SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"), updated_at=updated
    )
    doc_b = SimpleNamespace(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"), updated_at=updated
    )
    forward = space_intelligence_signature([doc_a, doc_b])
    reverse = space_intelligence_signature([doc_b, doc_a])
    assert forward == reverse
    assert len(forward) == 64
    assert all(character in "0123456789abcdef" for character in forward)

    changed = SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        updated_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert space_intelligence_signature([changed, doc_b]) != forward
