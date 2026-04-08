from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.core.config import settings


def _uuid() -> str:
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class VectorType(UserDefinedType):
    cache_ok = True

    def __init__(self, dimension: int):
        self.dimension = dimension

    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimension})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return "[" + ",".join(f"{float(item):.8f}" for item in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            stripped = str(value).strip().strip("[]")
            if not stripped:
                return []
            return [float(item) for item in stripped.split(",")]

        return process


class NormativeSource(Base, TimestampMixin):
    __tablename__ = "normative_sources"
    __table_args__ = (
        UniqueConstraint("project_key", "source_key", "version", name="uq_normative_source_project_key_version"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_key: Mapped[str] = mapped_column(String(64), default="recalculation", nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="published", nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    file_size: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str | None] = mapped_column(String(512))
    content_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class AppealClassificationRule(Base, TimestampMixin):
    __tablename__ = "appeal_classification_rules"
    __table_args__ = (
        UniqueConstraint("project_key", "appeal_class", "version", name="uq_classification_rule_project_class_version"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_key: Mapped[str] = mapped_column(String(64), default="recalculation", nullable=False, index=True)
    appeal_class: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    requester_type: Mapped[str | None] = mapped_column(String(32))
    authority_type: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    match_terms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LetterTemplate(Base, TimestampMixin):
    __tablename__ = "letter_templates"
    __table_args__ = (
        UniqueConstraint("project_key", "template_key", "version", name="uq_letter_template_project_key_version"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_key: Mapped[str] = mapped_column(String(64), default="recalculation", nullable=False, index=True)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    paragraphs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CanonicalAttribute(Base, TimestampMixin):
    __tablename__ = "canonical_attributes"
    __table_args__ = (
        UniqueConstraint("domain", "normalized_name", name="uq_canonical_attribute_domain_name"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    domain: Mapped[str] = mapped_column(String(64), default="technical_compliance", nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    unit: Mapped[str | None] = mapped_column(String(64))
    value_type: Mapped[str] = mapped_column(String(64), default="string", nullable=False)
    synonyms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class KnowledgeChunk(Base, TimestampMixin):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "chunk_index", name="uq_knowledge_chunk_source_index"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_key: Mapped[str] = mapped_column(String(64), default="recalculation", nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(VectorType(settings.KNOWLEDGE_BASE_EMBEDDING_DIM))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_key: Mapped[str] = mapped_column(String(64), default="shared", nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
