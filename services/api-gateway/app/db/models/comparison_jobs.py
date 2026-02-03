from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func, text

from app.db.base import Base


class ComparisonJob(Base):
    __tablename__ = "comparison_job"
    __table_args__ = (
        UniqueConstraint("analysis_id", name="uq_comparison_job"),
        {"schema": "analysis"},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String, nullable=False, server_default=text("'queued'"))
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text, nullable=True)
    result = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)


__all__ = ["ComparisonJob"]
