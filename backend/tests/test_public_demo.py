import pytest

from app.config import settings
from app.demo_fixtures import (
    COMPARISON_ID,
    DEMO_SPACE_ID,
    MEMBERSHIP_DOCUMENT_ID,
    demo_actions,
    demo_analysis,
    demo_comparison,
    demo_documents,
    demo_intelligence,
    demo_space,
)


def test_demo_fixtures_are_deterministic_and_synthetic():
    assert demo_space()["id"] == DEMO_SPACE_ID
    documents = demo_documents()
    assert len(documents) == 3
    assert all("Northwind" in document["original_filename"] for document in documents)
    assert demo_analysis(MEMBERSHIP_DOCUMENT_ID)["provider"] == "demo-fixture"
    assert demo_actions(MEMBERSHIP_DOCUMENT_ID)["status"] == "ready"
    assert demo_comparison()["id"] == COMPARISON_ID
    assert demo_intelligence()["ready_document_count"] == 2


@pytest.mark.asyncio
async def test_public_demo_serves_read_only_pre_generated_data(async_client, monkeypatch):
    monkeypatch.setattr(settings, "public_demo_mode", True)

    space_response = await async_client.get("/public-demo/space")
    assert space_response.status_code == 200
    assert space_response.json()["name"] == "Northwind Workspace"

    documents_response = await async_client.get("/public-demo/space/documents")
    assert documents_response.status_code == 200
    assert len(documents_response.json()) == 3

    ask_response = await async_client.post(
        "/public-demo/space/ask",
        json={"question": "What is the monthly membership fee?"},
    )
    assert ask_response.status_code == 200
    assert "CHF 420" in ask_response.json()["answer"]
    assert ask_response.json()["citations"][0]["document_id"] == str(MEMBERSHIP_DOCUMENT_ID)

    comparison_response = await async_client.get(f"/public-demo/space/comparisons/{COMPARISON_ID}")
    assert comparison_response.status_code == 200
    assert comparison_response.json()["dimensions"][0]["findings"][0]["sources"][0][
        "document_id"
    ] == str(MEMBERSHIP_DOCUMENT_ID)

    search_response = await async_client.get("/public-demo/search?q=CHF%20460")
    assert search_response.status_code == 200
    assert search_response.json()[0]["document_name"] == "Northwind_Renewal_Notice.pdf"

    unsupported_response = await async_client.post(
        "/public-demo/space/ask",
        json={"question": "Tell me something outside the examples"},
    )
    assert unsupported_response.status_code == 200
    assert unsupported_response.json()["supported"] is False
    assert "Live AI generation is disabled" in unsupported_response.json()["answer"]


@pytest.mark.asyncio
async def test_public_demo_blocks_private_mutations_before_provider_routes(
    async_client, monkeypatch
):
    monkeypatch.setattr(settings, "public_demo_mode", True)

    paths = [
        f"/knowledge-spaces/{DEMO_SPACE_ID}/documents/{MEMBERSHIP_DOCUMENT_ID}/analysis",
        f"/knowledge-spaces/{DEMO_SPACE_ID}/documents/{MEMBERSHIP_DOCUMENT_ID}/actions",
        f"/knowledge-spaces/{DEMO_SPACE_ID}/intelligence",
        "/auth/login",
    ]
    for path in paths:
        response = await async_client.post(path, json={})
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]


@pytest.mark.asyncio
async def test_public_demo_routes_are_not_public_when_disabled(async_client):
    assert settings.public_demo_mode is False
    response = await async_client.get("/public-demo/space")
    assert response.status_code == 404
