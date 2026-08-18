import json
import uuid

import httpx
import pytest

from app.domain.analysis import (
    AnalysisSource,
    DocumentAnalysisContext,
    ProviderDocumentAnalysis,
)
from app.domain.errors import ProviderError
from app.infrastructure.analysis_providers import (
    DeepSeekDocumentAnalysisProvider,
    DeterministicAnalysisProvider,
)

BASE_URL = "https://api.deepseek.com"


def context(sources: list[str] | None = None) -> DocumentAnalysisContext:
    return DocumentAnalysisContext(
        document_id=uuid.uuid4(),
        sources=[
            AnalysisSource(
                source_id=f"chunk:{uuid.uuid4()}",
                page_number=index + 1,
                content=content,
            )
            for index, content in enumerate(
                sources
                or ["Service Agreement between the parties.", "Termination requires 30 days."]
            )
        ],
    )


def provider_with_transport(monkeypatch, handler) -> DeepSeekDocumentAnalysisProvider:
    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(transport=transport, *args, **kwargs),
    )
    return DeepSeekDocumentAnalysisProvider(
        api_key="test-key",
        model_name="deepseek-chat",
        base_url=BASE_URL,
        timeout_seconds=5,
    )


def deepseek_result() -> dict:
    return {
        "document_type": "contract",
        "normalized_title": "Service Agreement",
        "summary": "A service agreement with a 30 day termination notice.",
        "important_dates": [
            {
                "label": "Effective date",
                "value": "1 September 2026",
                "normalized_date": "2026-09-01",
                "source_ids": ["chunk:abc"],
            }
        ],
        "key_facts": [
            {
                "label": "Termination notice",
                "value": "30 days",
                "source_ids": ["chunk:abc"],
            }
        ],
    }


def wrap_content(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_deepseek_parses_valid_structured_analysis(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "deepseek-chat"
        assert body["response_format"] == {"type": "json_object"}
        assert "Service Agreement" in body["messages"][1]["content"]
        return wrap_content(json.dumps(deepseek_result()))

    provider = provider_with_transport(monkeypatch, handler)
    result = await provider.analyze(context())
    assert isinstance(result, ProviderDocumentAnalysis)
    assert result.document_type == "contract"
    assert result.normalized_title == "Service Agreement"
    assert result.important_dates[0].normalized_date == "2026-09-01"
    assert result.key_facts[0].value == "30 days"


@pytest.mark.asyncio
async def test_deepseek_prompt_requires_explicit_non_empty_json_contract(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        assert "exactly one valid JSON object" in prompt
        assert "exactly these five keys" in prompt
        assert "important_dates and key_facts must be arrays" in prompt
        assert "use [] when none" in prompt
        return wrap_content(json.dumps(deepseek_result()))

    provider = provider_with_transport(monkeypatch, handler)
    result = await provider.analyze(context())
    assert result.document_type == "contract"


@pytest.mark.asyncio
async def test_deepseek_accepts_null_normalized_title(monkeypatch):
    payload = deepseek_result()
    payload["normalized_title"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        return wrap_content(json.dumps(payload))

    provider = provider_with_transport(monkeypatch, handler)
    result = await provider.analyze(context())
    assert result.normalized_title == ""


@pytest.mark.asyncio
async def test_deepseek_rejects_non_json_content(monkeypatch):
    provider = provider_with_transport(monkeypatch, lambda request: wrap_content("not json"))
    with pytest.raises(ProviderError):
        await provider.analyze(context())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "document_type": 123,
            "normalized_title": "x",
            "summary": "s",
            "important_dates": [],
            "key_facts": [],
        },
        {
            "document_type": "contract",
            "normalized_title": 5,
            "summary": "s",
            "important_dates": [],
            "key_facts": [],
        },
        {
            "document_type": "contract",
            "normalized_title": "x",
            "summary": "s",
            "important_dates": "wrong",
            "key_facts": [],
        },
        {
            "document_type": "contract",
            "normalized_title": "x",
            "summary": "s",
            "important_dates": [],
            "key_facts": "wrong",
        },
        {
            "document_type": "contract",
            "normalized_title": "x",
            "summary": "s",
            "important_dates": [
                {
                    "label": "d",
                    "value": "1 September 2026",
                    "normalized_date": "2026-09-01",
                    "source_ids": "not-a-list",
                }
            ],
            "key_facts": [],
        },
        {
            "document_type": "contract",
            "normalized_title": "x",
            "summary": "s",
            "important_dates": [],
            "key_facts": [{"label": "f", "value": "v", "source_ids": [1]}],
        },
    ],
)
async def test_deepseek_rejects_malformed_structures(monkeypatch, payload):
    provider = provider_with_transport(
        monkeypatch, lambda request: wrap_content(json.dumps(payload))
    )
    with pytest.raises(ProviderError):
        await provider.analyze(context())


@pytest.mark.asyncio
async def test_deepseek_surfaces_http_errors(monkeypatch):
    provider = provider_with_transport(
        monkeypatch, lambda request: httpx.Response(500, json={"error": "boom"})
    )
    with pytest.raises(ProviderError):
        await provider.analyze(context())


@pytest.mark.asyncio
async def test_deepseek_requires_api_key():
    with pytest.raises(ProviderError):
        DeepSeekDocumentAnalysisProvider(
            api_key="",
            model_name="deepseek-chat",
            base_url=BASE_URL,
            timeout_seconds=5,
        )


@pytest.mark.asyncio
async def test_deterministic_provider_classifies_insurance():
    provider = DeterministicAnalysisProvider()
    result = await provider.analyze(
        context(["Home Insurance Policy 2026.", "This policy expires on 31 January 2027."])
    )
    assert result.document_type == "insurance_policy"
    assert result.important_dates[0].label == "Expiration date"
    assert result.important_dates[0].value == "31 January 2027"
    assert result.important_dates[0].normalized_date == "2027-01-31"


@pytest.mark.asyncio
async def test_deterministic_provider_classifies_contract():
    provider = DeterministicAnalysisProvider()
    result = await provider.analyze(
        context(
            [
                "Service Agreement between the parties.",
                "Effective 1 September 2026. Termination notice: 30 days notice is required.",
                "Total contract value: $250,000.",
            ]
        )
    )
    assert result.document_type == "contract"
    assert result.normalized_title.startswith("Service Agreement")
    assert any(d.label == "Effective date" for d in result.important_dates)
    assert any(f.label == "Termination notice" for f in result.key_facts)


@pytest.mark.asyncio
async def test_deterministic_provider_returns_unknown_for_general_text():
    provider = DeterministicAnalysisProvider()
    result = await provider.analyze(
        context(["Meeting notes from the research team about next quarter."])
    )
    assert result.document_type == "unknown"
