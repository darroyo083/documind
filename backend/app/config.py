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

    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384

    deepseek_base_url: str = "https://api.deepseek.com"
    provider_timeout_seconds: float = 30.0

    default_top_k: int = 5
    retrieval_max_top_k: int = 10
    default_similarity_threshold: float = 0.2
    max_question_length: int = 1000

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
