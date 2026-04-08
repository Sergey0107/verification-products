from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _create_engine() -> Engine:
    connect_args = {"check_same_thread": False} if _is_sqlite(settings.KNOWLEDGE_BASE_DB_URL) else {}
    return create_engine(
        settings.KNOWLEDGE_BASE_DB_URL,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ping_db() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def is_postgres() -> bool:
    return settings.KNOWLEDGE_BASE_DB_URL.startswith("postgresql")
