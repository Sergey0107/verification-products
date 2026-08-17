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
    SQL_ECHO: bool = False
    SESSION_EXPIRE_MINUTES: int = 8 * 60
    SESSION_COOKIE_NAME: str = "ivolga_session"
    CSRF_COOKIE_NAME: str = "ivolga_csrf"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: str | None = None
    # Общий секрет для внутренних callback'ов (/files/callback,
    # /compare/callback, /internal/extraction-callback). Они не проходят
    # пользовательскую аутентификацию (их дёргают сервисы, а не браузер), а
    # nginx проксирует наружу весь префикс /files/ — то есть /files/callback
    # был доступен анониму из интернета: позволял подменить storage_path
    # (чтение чужих файлов через presign), уронить чужой анализ в failed и
    # запустить платный LLM-пайплайн. Тот же заголовок шлют file-service,
    # domain-analyze и paddleocr-vl-service. Пустое значение = проверка
    # выключена (для локальной разработки); в проде задаётся в env/.env.
    INTERNAL_CALLBACK_SECRET: str = ""
    INTERNAL_CALLBACK_HEADER: str = "X-Internal-Secret"
    PROMPT_REGISTRY_URL: str = "http://prompt-registry:8000"
    EXTRACTION_SERVICE_URL: str = "http://extraction-service:8000"
    EXTRACTION_BACKEND: str = "mineru"
    # Тот же флаг, что читает extraction-service. Нужен здесь, чтобы фронтенд
    # мог узнать, доступен ли paddleocr_vl: сервис требует GPU и поднимается
    # только локально, на сервере опции быть не должно.
    PADDLEOCR_VL_ENABLED: bool = False
    # Прямой URL к paddleocr-vl-service — используется ТОЛЬКО fallback-
    # поллингом (poll_stuck_extraction_jobs в tasks.py) для проверки статуса
    # async-job'ов через GET /jobs/{id}, когда callback от него не дошёл.
    # Основной путь данных (сам запуск/результат извлечения) всегда идёт
    # через extraction-service — эта переменная не даёт api-gateway новых
    # прав вызывать extraction-логику напрямую, только читать job-статус.
    PADDLEOCR_VL_SERVICE_URL: str = "http://paddleocr-vl-service:8000"
    # Порог "давно не обновлялся" для fallback-поллинга — с запасом над
    # интервалом между попытками callback (см. CALLBACK_MAX_ATTEMPTS в
    # job_queue.py, суммарно там до ~3.5 минут задержек между 6 попытками)
    # и над обычным временем самой обработки, чтобы не дёргать paddleocr-vl-
    # service статус-запросами по job'ам, которые просто ещё работают.
    STUCK_EXTRACTION_JOB_THRESHOLD_SECONDS: int = 600
    KNOWLEDGE_BASE_URL: str = "http://knowledge-base:8000"
    KNOWLEDGE_BASE_TIMEOUT_SECONDS: int = 5
    DOMAIN_ANALYZE_URL: str = "http://domain-analyze:8000"
    FILE_SERVICE_URL: str = "http://file-service:8000"
    S3_ENDPOINT: str = "https://storage.yandexcloud.net"
    BUCKET_NAME: str = ""
    EXTRACTION_TIMEOUT_SECONDS: int = 2400
    CELERY_BROKER_URL: str = "amqp://guest:guest@rabbitmq:5672//"
    CELERY_RESULT_BACKEND: str = "rpc://"
    EXTRACTION_DEBUG_DIR: str = "/tmp"
    COMP_DATA_DIR: str = "/comp_data"
    # Сырой OCR+LLM-structuring ответ paddleocr-vl-service (до конвертации в
    # products) — по одному файлу на (analysis_id, file_type), перезаписывается
    # при повторном извлечении. Пишет api-gateway-worker (там выполняется
    # finalize_extraction_task/postprocess_extraction_result — Celery-задачи),
    # читает api-gateway (HTTP-эндпоинт скачивания) — это РАЗНЫЕ контейнеры с
    # разными изолированными /tmp, поэтому путь обязан лежать на volume,
    # который смонтирован в обоих (см. docker-compose.yml: comp_data уже
    # общий для api-gateway и api-gateway-worker — переиспользуем его, а не
    # заводим отдельный volume).
    RAW_OCR_DIR: str = "/comp_data/raw_ocr"


settings = Settings()
