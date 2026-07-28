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
    # Провайдер по умолчанию для сравнения (AI Tunnel через OpenAI-совместимый
    # API). Используется, когда анализ создан без выбора backend или с
    # backend'ом, у которого нет своей LLM.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openai/gpt-4.1"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Модель именно для сравнения. Отдельная от OPENROUTER_MODEL, потому что ту
    # же переменную читает extraction-service для извлечения — менять её здесь
    # значило бы менять и модель извлечения. Пустое значение = взять
    # OPENROUTER_MODEL (поведение до появления этой настройки).
    AITUNNEL_COMPARE_MODEL: str = ""

    # Yandex AI Studio — используется, когда анализ запущен с извлечением
    # yandex_vision_ocr: тогда оба этапа (извлечение и сравнение) идут через
    # Yandex, а не через AI Tunnel.
    YANDEX_API_KEY: str = ""
    YANDEX_FOLDER_ID: str = ""
    YANDEX_BASE_URL: str = "https://llm.api.cloud.yandex.net/v1"
    # qwen3-235b-a22b-fp8 — самая крупная текстовая модель, доступная в этом
    # каталоге AI Studio. Сравнение характеристик требует понимания
    # формулировок и единиц, поэтому flash-модели здесь слабоваты.
    YANDEX_COMPARE_MODEL: str = "qwen3-235b-a22b-fp8"
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
