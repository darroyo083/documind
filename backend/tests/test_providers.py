import json
import uuid

import httpx
import pytest

from app.domain.errors import ProviderError
from app.domain.rag import RetrievedChunk
from app.infrastructure.providers import DeepSeekAnswerProvider

BASE_URL = "https://api.deepseek.com"


def chunk(source_id: str = "chunk:abc") -> RetrievedChunk:
    return RetrievedChunk(
        source_id=source_id,
        source_kind="private",
        document_id=str(uuid.uuid4()),
        document_name="evidence.pdf",
        page_number=1,
        chunk_id=str(uuid.uuid4()),
        content="DocuMind evidence content.",
        score=0.9,
    )


def provider_with_transport(monkeypatch, handler) -> DeepSeekAnswerProvider:
    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(transport=transport, *args, **kwargs),
    )
    return DeepSeekAnswerProvider(
        api_key="test-key",
        model_name="deepseek-chat",
        base_url=BASE_URL,
        timeout_seconds=5,
    )


@pytest.mark.asyncio
async def test_deepseek_parses_valid_structured_response(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "deepseek-chat"
        assert body["response_format"] == {"type": "json_object"}
        assert "DocuMind evidence content" in body["messages"][1]["content"]
        assert "including the private: or reference: prefix" in body["messages"][0]["content"]
        assert "out of answer prose" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "DocuMind evidence content.",
                                    "supported": True,
                                    "citation_source_ids": ["chunk:abc"],
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = provider_with_transport(monkeypatch, handler)
    result = await provider.answer("What is DocuMind?", [chunk()])
    assert result.answer == "DocuMind evidence content."
    assert result.supported is True
    assert result.citation_source_ids == ["chunk:abc"]


@pytest.mark.asyncio
async def test_deepseek_accepts_unsupported_response(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"answer": "", "supported": False, "citation_source_ids": []}
                            )
                        }
                    }
                ]
            },
        )

    provider = provider_with_transport(monkeypatch, handler)
    result = await provider.answer("Unknown topic", [chunk()])
    assert result.supported is False


@pytest.mark.asyncio
async def test_deepseek_rejects_non_json_content(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not json at all"}}]},
        )

    provider = provider_with_transport(monkeypatch, handler)
    with pytest.raises(ProviderError):
        await provider.answer("What?", [chunk()])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"answer": 123, "supported": True, "citation_source_ids": ["chunk:abc"]},
        {"answer": "text", "supported": "yes", "citation_source_ids": ["chunk:abc"]},
        {"answer": "text", "supported": True, "citation_source_ids": "chunk:abc"},
        {"answer": "text", "supported": True, "citation_source_ids": [123]},
    ],
)
async def test_deepseek_rejects_malformed_structured_response(monkeypatch, payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    provider = provider_with_transport(monkeypatch, handler)
    with pytest.raises(ProviderError):
        await provider.answer("What?", [chunk()])


@pytest.mark.asyncio
async def test_deepseek_surfaces_http_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = provider_with_transport(monkeypatch, handler)
    with pytest.raises(ProviderError):
        await provider.answer("What?", [chunk()])


@pytest.mark.asyncio
async def test_deepseek_requires_api_key():
    with pytest.raises(ProviderError):
        DeepSeekAnswerProvider(
            api_key="",
            model_name="deepseek-chat",
            base_url=BASE_URL,
            timeout_seconds=5,
        )
