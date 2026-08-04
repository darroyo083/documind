import json
import uuid

import httpx
import pytest

from app.domain.actions import (
    AnalysisSource,
    DocumentActionContext,
    ProviderDocumentActions,
)
from app.domain.errors import ProviderError
from app.infrastructure.action_providers import (
    DeepSeekDocumentActionProvider,
    DeterministicActionProvider,
)

BASE_URL = "https://api.deepseek.com"


def context(sources: list[str] | None = None) -> DocumentActionContext:
    return DocumentActionContext(
        document_id=str(uuid.uuid4()),
        sources=[
            AnalysisSource(
                source_id=f"chunk:{uuid.uuid4()}",
                page_number=index + 1,
                content=content,
            )
            for index, content in enumerate(sources or ["Payment is due by 31 January 2027."])
        ],
    )


def provider_with_transport(monkeypatch, handler) -> DeepSeekDocumentActionProvider:
    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(transport=transport, *args, **kwargs),
    )
    return DeepSeekDocumentActionProvider(
        api_key="test-key",
        model_name="deepseek-chat",
        base_url=BASE_URL,
        timeout_seconds=5,
    )


def deepseek_result() -> dict:
    return {
        "actions": [
            {
                "action_type": "deadline",
                "title": "Pay the invoice",
                "description": "Payment must be received.",
                "timing_text": "31 January 2027",
                "due_date": "2027-01-31",
                "source_ids": ["chunk:abc"],
            }
        ]
    }


def wrap_content(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_deepseek_parses_valid_action_response(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "deepseek-chat"
        assert body["response_format"] == {"type": "json_object"}
        assert "Payment is due by" in body["messages"][1]["content"]
        return wrap_content(json.dumps(deepseek_result()))

    provider = provider_with_transport(monkeypatch, handler)
    result = await provider.generate_actions(context())
    assert isinstance(result, ProviderDocumentActions)
    assert result.actions[0].action_type == "deadline"
    assert result.actions[0].title == "Pay the invoice"
    assert result.actions[0].due_date == "2027-01-31"


@pytest.mark.asyncio
async def test_deepseek_accepts_empty_actions(monkeypatch):
    provider = provider_with_transport(
        monkeypatch, lambda request: wrap_content(json.dumps({"actions": []}))
    )
    result = await provider.generate_actions(context())
    assert result.actions == []


@pytest.mark.asyncio
async def test_deepseek_rejects_non_json_content(monkeypatch):
    provider = provider_with_transport(monkeypatch, lambda request: wrap_content("not json"))
    with pytest.raises(ProviderError):
        await provider.generate_actions(context())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"actions": "wrong"},
        {"actions": [{"action_type": 1, "title": "x", "source_ids": []}]},
        {"actions": [{"action_type": "deadline", "title": 5, "source_ids": []}]},
        {"actions": [{"action_type": "deadline", "title": "x", "source_ids": "nope"}]},
        {"actions": [{"action_type": "deadline", "title": "x", "source_ids": [1]}]},
        {"actions": [{"action_type": "deadline", "title": "x", "source_ids": [], "due_date": 5}]},
        {
            "actions": [
                {"action_type": "deadline", "title": "x", "source_ids": [], "description": 5}
            ]
        },
    ],
)
async def test_deepseek_rejects_malformed_structures(monkeypatch, payload):
    provider = provider_with_transport(
        monkeypatch, lambda request: wrap_content(json.dumps(payload))
    )
    with pytest.raises(ProviderError):
        await provider.generate_actions(context())


@pytest.mark.asyncio
async def test_deepseek_surfaces_http_errors(monkeypatch):
    provider = provider_with_transport(
        monkeypatch, lambda request: httpx.Response(500, json={"error": "boom"})
    )
    with pytest.raises(ProviderError):
        await provider.generate_actions(context())


@pytest.mark.asyncio
async def test_deepseek_requires_api_key():
    with pytest.raises(ProviderError):
        DeepSeekDocumentActionProvider(
            api_key="",
            model_name="deepseek-chat",
            base_url=BASE_URL,
            timeout_seconds=5,
        )


@pytest.mark.asyncio
async def test_deterministic_provider_required_action():
    provider = DeterministicActionProvider()
    result = await provider.generate_actions(
        context(["Cancellation requires written notice at least 30 days in advance."])
    )
    assert result.actions[0].action_type == "required_action"
    assert result.actions[0].title == "Send written cancellation notice"
    assert result.actions[0].timing_text == "At least 30 days before cancellation"
    assert result.actions[0].due_date is None


@pytest.mark.asyncio
async def test_deterministic_provider_deadline():
    provider = DeterministicActionProvider()
    result = await provider.generate_actions(context(["Payment is due by 31 January 2027."]))
    assert result.actions[0].action_type == "deadline"
    assert result.actions[0].title == "Pay the invoice"
    assert result.actions[0].due_date == "2027-01-31"


@pytest.mark.asyncio
async def test_deterministic_provider_reminder():
    provider = DeterministicActionProvider()
    result = await provider.generate_actions(
        context(["The policy renews automatically on 1 March 2027."])
    )
    assert result.actions[0].action_type == "reminder"
    assert result.actions[0].title == "Policy renewal date"
    assert result.actions[0].due_date is None


@pytest.mark.asyncio
async def test_deterministic_provider_recommended():
    provider = DeterministicActionProvider()
    result = await provider.generate_actions(
        context(["We recommend reviewing your beneficiary information annually."])
    )
    assert result.actions[0].action_type == "recommended_action"
    assert result.actions[0].title == "Review beneficiary information annually"


@pytest.mark.asyncio
async def test_deterministic_provider_no_actions_for_general_text():
    provider = DeterministicActionProvider()
    result = await provider.generate_actions(
        context(["Meeting notes about the quarterly planning session."])
    )
    assert result.actions == []
