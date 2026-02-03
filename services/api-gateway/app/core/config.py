from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    candidates = [Path.cwd() / "env" / ".env"]
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "env" / ".env")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    model_config = (
        SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8")
        if ENV_FILE
        else SettingsConfigDict()
    )
    DATABASE_URL: str = "postgresql+asyncpg://analyzer:analyzer@localhost:5432/analyzer"
    SECRET_KEY: str = "change_me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    PROMPT_REGISTRY_URL: str = "http://prompt-registry:8000"
    EXTRACTION_SERVICE_URL: str = "http://extraction-service:8000"
    DOMAIN_ANALYZE_URL: str = "http://domain-analyze:8000"
    S3_ENDPOINT: str = "https://storage.yandexcloud.net"
    BUCKET_NAME: str = ""
    EXTRACTION_TIMEOUT_SECONDS: int = 600
    CELERY_BROKER_URL: str = "amqp://guest:guest@rabbitmq:5672//"
    CELERY_RESULT_BACKEND: str = "rpc://"
    EXTRACTION_DEBUG_DIR: str = "/tmp"
    COMP_DATA_DIR: str = "/comp_data"


settings = Settings()
