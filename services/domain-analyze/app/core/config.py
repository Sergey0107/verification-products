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
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openai/gpt-4.1"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    PROMPT_REGISTRY_URL: str = "http://prompt-registry:8000"
    KNOWLEDGE_BASE_URL: str = "http://knowledge-base:8000"
    KNOWLEDGE_BASE_TIMEOUT_SECONDS: int = 5
    API_GATEWAY_URL: str = "http://api-gateway:8000"
    CELERY_BROKER_URL: str = "amqp://guest:guest@rabbitmq:5672//"
    CELERY_RESULT_BACKEND: str = "rpc://"
    # Ответ LLM на chunk сравнения реально занимает 36-172 сек (замерено по
    # логам на реальных документах: reasoning-модель тратит часть времени на
    # рассуждение до финального JSON). 120 сек оказывались ровно посередине
    # этого диапазона — часть запросов стабильно падала с ReadTimeout, и
    # анализ обрывался ошибкой "The read operation timed out". 300 даёт
    # реальный запас над наблюдаемым максимумом.
    REQUEST_TIMEOUT_SECONDS: int = 300
    # Меньше характеристик в одном запросе — меньше reasoning-токенов и
    # быстрее ответ, плюс при сбое теряется меньше работы (раньше падение
    # одного запроса стоило всех 120 характеристик разом).
    COMPARE_CHUNK_SIZE: int = 50
    COMPARE_CHUNK_DELAY_SECONDS: float = 0.6


settings = Settings()
