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

    generation_provider: str = "mock"
    generation_model: str = "mock-model"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    embedding_provider: str = "mock"
    embedding_model: str = "mock-model"

    default_top_k: int = 5
    default_similarity_threshold: float = 0.5

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
