from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
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
    status = Column(String, nullable=False)
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


__all__ = ["Analysis", "ComparisonRow", "UserEdit"]
