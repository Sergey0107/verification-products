from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://analyzer:analyzer@localhost:5432/analyzer"
    SECRET_KEY: str = "change_me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    PROMPT_REGISTRY_URL: str = "http://prompt-registry:8000"
    EXTRACTION_SERVICE_URL: str = "http://extraction-service:8000"
    DOMAIN_ANALYZE_URL: str = "http://domain-analyze:8000"
    S3_ENDPOINT: str = "https://storage.yandexcloud.net"
    BUCKET_NAME: str = ""
    EXTRACTION_TIMEOUT_SECONDS: int = 60
    CELERY_BROKER_URL: str = "amqp://guest:guest@rabbitmq:5672//"
    CELERY_RESULT_BACKEND: str = "rpc://"
    EXTRACTION_DEBUG_DIR: str = "/tmp"
    COMP_DATA_DIR: str = "/comp_data"


settings = Settings()
