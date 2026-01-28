from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func, text
from pgvector.sqlalchemy import Vector
from app.db.base import Base


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entry"
    __table_args__ = {"schema": "knowledge"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source = Column(String, nullable=False)
    content = Column(JSONB, nullable=False)
    embedding = Column(Vector(1536))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


__all__ = ["KnowledgeEntry"]