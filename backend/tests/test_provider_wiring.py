"""Offline provider-selection tests for the OpenCode Go wiring.

Verifies each generative feature can select the OpenCode Go transport (the same
generic OpenAI-compatible adapter) with the correct model/base URL, without any
network call. Mirrors ``test_opencode_go_provider_selection`` in
``test_comparison_providers.py``.
"""

from app.application.dependencies import (
    get_action_provider,
    get_analysis_provider,
    get_answer_provider,
    get_intelligence_provider,
)
from app.config import settings
from app.infrastructure.action_providers import DeepSeekDocumentActionProvider
from app.infrastructure.analysis_providers import DeepSeekDocumentAnalysisProvider
from app.infrastructure.intelligence_providers import OpenCodeGoSpaceIntelligenceProvider
from app.infrastructure.providers import DeepSeekAnswerProvider


def test_answer_provider_opencode_go_selection(monkeypatch):
    monkeypatch.setattr(settings, "generation_provider", "opencode-go")
    monkeypatch.setattr(settings, "opencode_go_api_key", "test-key")
    get_answer_provider.cache_clear()
    try:
        provider = get_answer_provider()
        assert isinstance(provider, DeepSeekAnswerProvider)
        assert provider.model_name == "deepseek-v4-flash"
        assert provider.base_url == "https://opencode.ai/zen/go/v1"
    finally:
        get_answer_provider.cache_clear()


def test_analysis_provider_opencode_go_selection(monkeypatch):
    monkeypatch.setattr(settings, "analysis_provider", "opencode-go")
    monkeypatch.setattr(settings, "opencode_go_api_key", "test-key")
    get_analysis_provider.cache_clear()
    try:
        provider = get_analysis_provider()
        assert isinstance(provider, DeepSeekDocumentAnalysisProvider)
        assert provider.model_name == "deepseek-v4-flash"
        assert provider.base_url == "https://opencode.ai/zen/go/v1"
    finally:
        get_analysis_provider.cache_clear()


def test_action_provider_opencode_go_selection(monkeypatch):
    monkeypatch.setattr(settings, "action_provider", "opencode-go")
    monkeypatch.setattr(settings, "opencode_go_api_key", "test-key")
    get_action_provider.cache_clear()
    try:
        provider = get_action_provider()
        assert isinstance(provider, DeepSeekDocumentActionProvider)
        assert provider.model_name == "deepseek-v4-flash"
        assert provider.base_url == "https://opencode.ai/zen/go/v1"
    finally:
        get_action_provider.cache_clear()


def test_intelligence_provider_opencode_go_selection(monkeypatch):
    monkeypatch.setattr(settings, "intelligence_provider", "opencode-go")
    monkeypatch.setattr(settings, "opencode_go_api_key", "test-key")
    get_intelligence_provider.cache_clear()
    try:
        provider = get_intelligence_provider()
        assert isinstance(provider, OpenCodeGoSpaceIntelligenceProvider)
        assert provider.model_name == "deepseek-v4-flash"
        assert provider.base_url == "https://opencode.ai/zen/go/v1"
    finally:
        get_intelligence_provider.cache_clear()
