from pydantic import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://analyzer:analyzer@localhost:5432/analyzer"


settings = Settings()
