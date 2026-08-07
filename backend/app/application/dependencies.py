from functools import lru_cache

from app.config import settings
from app.domain.actions import DocumentActionProvider
from app.domain.analysis import DocumentAnalysisProvider
from app.domain.comparison import DocumentComparisonProvider
from app.domain.errors import ProviderError
from app.domain.rag import AnswerProvider, DocumentStorage, EmbeddingProvider
from app.infrastructure.action_providers import (
    DeepSeekDocumentActionProvider,
    DeterministicActionProvider,
)
from app.infrastructure.analysis_providers import (
    DeepSeekDocumentAnalysisProvider,
    DeterministicAnalysisProvider,
)
from app.infrastructure.comparison_providers import (
    DeepSeekDocumentComparisonProvider,
    DeterministicComparisonProvider,
    OpenCodeGoDocumentComparisonProvider,
)
from app.infrastructure.providers import (
    DeepSeekAnswerProvider,
    DeterministicAnswerProvider,
    DeterministicEmbeddingProvider,
    FastEmbedProvider,
)
from app.infrastructure.storage import LocalDocumentStorage


@lru_cache
def get_document_storage() -> DocumentStorage:
    return LocalDocumentStorage(settings.upload_dir)


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    if settings.embedding_provider == "mock":
        return DeterministicEmbeddingProvider(settings.embedding_dimension)
    if settings.embedding_provider == "local":
        return FastEmbedProvider(settings.embedding_model, settings.embedding_dimension)
    raise ProviderError("Unsupported embedding provider configuration")


@lru_cache
def get_answer_provider() -> AnswerProvider:
    if settings.generation_provider == "mock":
        return DeterministicAnswerProvider()
    if settings.generation_provider == "deepseek":
        return DeepSeekAnswerProvider(
            api_key=settings.deepseek_api_key,
            model_name=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
        )
    raise ProviderError("Unsupported answer provider configuration")


@lru_cache
def get_analysis_provider() -> DocumentAnalysisProvider:
    if settings.analysis_provider == "mock":
        return DeterministicAnalysisProvider()
    if settings.analysis_provider == "deepseek":
        return DeepSeekDocumentAnalysisProvider(
            api_key=settings.deepseek_api_key,
            model_name=settings.analysis_model,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
        )
    raise ProviderError("Unsupported document analysis provider configuration")


@lru_cache
def get_action_provider() -> DocumentActionProvider:
    if settings.action_provider == "mock":
        return DeterministicActionProvider()
    if settings.action_provider == "deepseek":
        return DeepSeekDocumentActionProvider(
            api_key=settings.deepseek_api_key,
            model_name=settings.action_model,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
        )
    raise ProviderError("Unsupported document action provider configuration")


@lru_cache
def get_comparison_provider() -> DocumentComparisonProvider:
    if settings.comparison_provider == "mock":
        return DeterministicComparisonProvider()
    if settings.comparison_provider == "deepseek":
        return DeepSeekDocumentComparisonProvider(
            api_key=settings.deepseek_api_key,
            model_name=settings.comparison_model,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
        )
    if settings.comparison_provider == "opencode-go":
        return OpenCodeGoDocumentComparisonProvider(
            api_key=settings.opencode_go_api_key,
            model_name=settings.comparison_model,
            base_url=settings.opencode_go_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
        )
    raise ProviderError("Unsupported document comparison provider configuration")
