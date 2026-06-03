from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func, text
from app.db.base import Base


class Analysis(Base):
    __tablename__ = "analysis"
    __table_args__ = {"schema": "analysis"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user.id"), nullable=True)
    status = Column(String, nullable=False)
    extraction_backend = Column(String, nullable=False, server_default=text("'openrouter'"))
    task_id = Column(String, nullable=True)
    product_model = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)


class ComparisonRow(Base):
    __tablename__ = "comparison_row"
    __table_args__ = {"schema": "analysis"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    characteristic = Column(String, nullable=False)
    tz_value = Column(Text)
    passport_value = Column(Text)
    tz_quote = Column(Text)
    passport_quote = Column(Text)
    tz_evidence = Column(JSONB)
    passport_evidence = Column(JSONB)
    llm_result = Column(Boolean)
    user_result = Column(Boolean, server_default=text("true"))
    note = Column(String)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class UserEdit(Base):
    __tablename__ = "user_edit"
    __table_args__ = {"schema": "analysis"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    comparison_row_id = Column(UUID(as_uuid=True), nullable=False)
    comment = Column(Text)
    edited_at = Column(DateTime, server_default=func.now(), nullable=False)


class TzCharacteristicReview(Base):
    __tablename__ = "tz_characteristic_review"
    __table_args__ = (
        UniqueConstraint("analysis_id", "characteristic_id", name="uq_tz_characteristic_review"),
        {"schema": "analysis"},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    characteristic_id = Column(String, nullable=False)
    product_name = Column(String, nullable=False)
    name = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    references = Column(JSONB, nullable=True)
    evidence = Column(JSONB, nullable=True)
    approved = Column(Boolean, nullable=False, server_default=text("true"))
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)


__all__ = ["Analysis", "ComparisonRow", "UserEdit", "TzCharacteristicReview"]
