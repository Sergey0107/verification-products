from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    PROMPT_REGISTRY_URL: str = "http://prompt-registry:8000"
    API_GATEWAY_URL: str = "http://api-gateway:8000"
    CELERY_BROKER_URL: str = "amqp://guest:guest@rabbitmq:5672//"
    CELERY_RESULT_BACKEND: str = "rpc://"
    REQUEST_TIMEOUT_SECONDS: int = 120
    COMPARE_CHUNK_SIZE: int = 120
    COMPARE_CHUNK_DELAY_SECONDS: float = 0.6


settings = Settings()
