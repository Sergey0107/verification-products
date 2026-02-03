from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func, text

from app.db.base import Base


class ExtractionResult(Base):
    __tablename__ = "extraction_result"
    __table_args__ = (
        UniqueConstraint("analysis_id", "file_type", name="uq_extraction_result"),
        {"schema": "analysis"},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    file_type = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)


__all__ = ["ExtractionResult"]
