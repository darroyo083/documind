from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "DocuMind"
    app_version: str = "0.1.0"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://documind:documind@localhost:5432/documind"

    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 1440

    upload_dir: str = "uploads"
    max_upload_size_mb: int = 10
    chunk_size: int = 800
    chunk_overlap: int = 120

    generation_provider: str = "mock"
    generation_model: str = "mock-model"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    analysis_provider: str = "mock"
    analysis_model: str = "deepseek-chat"
    analysis_max_context_chars: int = 120000
    analysis_max_important_dates: int = 10
    analysis_max_key_facts: int = 20
    analysis_max_label_length: int = 100
    analysis_max_value_length: int = 500
    analysis_max_summary_length: int = 2000
    analysis_max_sources_per_item: int = 8
    analysis_excerpt_chars: int = 2000

    action_provider: str = "mock"
    action_model: str = "deepseek-chat"
    action_max_context_chars: int = 120000
    action_max_items: int = 20
    action_max_title_length: int = 200
    action_max_description_length: int = 1000
    action_max_timing_length: int = 500
    action_max_sources_per_item: int = 8
    action_excerpt_chars: int = 2000

    comparison_provider: str = "mock"
    comparison_model: str = "deepseek-chat"
    opencode_go_api_key: str = ""
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"
    comparison_max_context_chars: int = Field(
        default=120000,
        gt=0,
        description=(
            "Max total characters of selected-document content sent to the "
            "comparison provider; values <= 0 would disable comparison generation."
        ),
    )
    comparison_max_focus_length: int = Field(
        default=500,
        gt=0,
        description="Max comparison-focus characters; values <= 0 would reject every focus.",
    )
    comparison_max_sources_per_item: int = Field(
        default=8,
        gt=0,
        description="Max validated source citations per comparison item.",
    )
    comparison_excerpt_chars: int = Field(
        default=2000,
        gt=0,
        description="Max characters of server-derived citation excerpts.",
    )

    intelligence_provider: str = "mock"
    intelligence_model: str = "deepseek-chat"
    intelligence_max_context_chars: int = Field(
        default=120000,
        gt=0,
        description=(
            "Max total characters of space-document content sent to the "
            "intelligence provider; values <= 0 would disable generation."
        ),
    )
    intelligence_max_documents: int = Field(
        default=20,
        gt=0,
        description="Max ready documents analyzed for a space intelligence snapshot.",
    )
    intelligence_max_sources_per_item: int = Field(
        default=8,
        gt=0,
        description="Max validated source citations per intelligence item.",
    )
    intelligence_excerpt_chars: int = Field(
        default=2000,
        gt=0,
        description="Max characters of intelligence citation excerpts.",
    )

    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384

    deepseek_base_url: str = "https://api.deepseek.com"
    provider_timeout_seconds: float = 30.0

    generation_stale_after_seconds: int = Field(
        default=900,
        gt=0,
        description=(
            "Processing lease timeout for generation flows; values <= 0 would make "
            "every processing row immediately stale (unsafe duplicate generation)."
        ),
    )

    default_top_k: int = 5
    retrieval_max_top_k: int = 10
    default_similarity_threshold: float = 0.2
    max_question_length: int = 1000

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
