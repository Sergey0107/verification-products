from pathlib import Path
import os

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


def _default_db_url() -> str:
    explicit = os.getenv("KNOWLEDGE_BASE_DB_URL")
    if explicit:
        return explicit
    postgres_user = os.getenv("POSTGRES_USER", "analyzer")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "analyzer")
    postgres_db = os.getenv("POSTGRES_DB", "analyzer")
    return f"postgresql+psycopg2://{postgres_user}:{postgres_password}@postgres:5432/{postgres_db}"


class Settings(BaseSettings):
    model_config = (
        SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8")
        if ENV_FILE
        else SettingsConfigDict()
    )

    APP_TITLE: str = "knowledge-base"
    LOG_LEVEL: str = "INFO"
    KNOWLEDGE_BASE_DB_URL: str = _default_db_url()
    KNOWLEDGE_BASE_BOOTSTRAP: bool = True
    KNOWLEDGE_BASE_STORAGE_DIR: str = "/data/knowledge-base"
    KNOWLEDGE_BASE_EMBEDDING_DIM: int = 256
    KNOWLEDGE_BASE_CHUNK_SIZE_CHARS: int = 1200
    KNOWLEDGE_BASE_CHUNK_OVERLAP_CHARS: int = 180


settings = Settings()
