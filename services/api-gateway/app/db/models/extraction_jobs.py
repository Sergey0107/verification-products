from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text

from app.db.base import Base


class ExtractionJob(Base):
    __tablename__ = "extraction_job"
    __table_args__ = (
        UniqueConstraint("analysis_id", "file_id", "file_type", name="uq_extraction_job"),
        {"schema": "analysis"},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    file_id = Column(UUID(as_uuid=True), nullable=False)
    file_type = Column(String, nullable=False)
    status = Column(String, nullable=False, server_default=text("'queued'"))
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)


__all__ = ["ExtractionJob"]
