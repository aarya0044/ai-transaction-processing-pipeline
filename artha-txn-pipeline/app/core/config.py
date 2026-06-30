import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://txn_user:txn_pass@postgres:5432/txn_db",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    celery_result_backend: str = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini")  # gemini | mock
    llm_model: str = os.getenv("LLM_MODEL", "gemini-1.5-flash")

    upload_dir: str = os.getenv("UPLOAD_DIR", "/data/uploads")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))

    class Config:
        env_file = ".env"


settings = Settings()
