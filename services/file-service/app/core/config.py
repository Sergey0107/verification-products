from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    S3_ENDPOINT: str = "https://storage.yandexcloud.net"
    S3_REGION: str = "ru-central1"
    BUCKET_NAME: str = ""
    AWS_KEY_ID: str = ""
    AWS_SECRET_KEY: str = ""
    CELERY_BROKER_URL: str = "amqp://guest:guest@rabbitmq:5672//"
    CELERY_RESULT_BACKEND: str = "rpc://"
    TMP_DIR: str = "/data/uploads"
    API_GATEWAY_URL: str = "http://api-gateway:8000"


settings = Settings()
