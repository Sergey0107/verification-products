from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LetterTemplateBase(BaseModel):
    project_key: str = "recalculation"
    template_key: str
    subject_template: str
    paragraphs: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    version: int = 1
    is_active: bool = True
    is_published: bool = True


class LetterTemplateCreate(LetterTemplateBase):
    pass


class LetterTemplateUpdate(BaseModel):
    subject_template: str | None = None
    paragraphs: list[str] | None = None
    variables: list[str] | None = None
    is_active: bool | None = None
    is_published: bool | None = None


class LetterTemplateRead(ORMModel, LetterTemplateBase):
    id: str
    is_system: bool
    created_at: datetime
    updated_at: datetime


class AppealClassificationRuleBase(BaseModel):
    project_key: str = "recalculation"
    appeal_class: str
    rule_name: str
    requester_type: str | None = None
    authority_type: str | None = None
    priority: int = 100
    version: int = 1
    description: str | None = None
    match_terms: list[str] = Field(default_factory=list)
    is_active: bool = True


class AppealClassificationRuleCreate(AppealClassificationRuleBase):
    pass


class AppealClassificationRuleUpdate(BaseModel):
    rule_name: str | None = None
    requester_type: str | None = None
    authority_type: str | None = None
    priority: int | None = None
    description: str | None = None
    match_terms: list[str] | None = None
    is_active: bool | None = None


class AppealClassificationRuleRead(ORMModel, AppealClassificationRuleBase):
    id: str
    is_system: bool
    created_at: datetime
    updated_at: datetime


class CanonicalAttributeBase(BaseModel):
    domain: str = "technical_compliance"
    name: str
    normalized_name: str
    unit: str | None = None
    value_type: str = "string"
    synonyms: list[str] = Field(default_factory=list)
    is_active: bool = True


class CanonicalAttributeCreate(CanonicalAttributeBase):
    pass


class CanonicalAttributeUpdate(BaseModel):
    name: str | None = None
    normalized_name: str | None = None
    unit: str | None = None
    value_type: str | None = None
    synonyms: list[str] | None = None
    is_active: bool | None = None


class CanonicalAttributeRead(ORMModel, CanonicalAttributeBase):
    id: str
    created_at: datetime
    updated_at: datetime


class NormativeSourceBase(BaseModel):
    project_key: str = "recalculation"
    source_key: str
    version: int = 1
    title: str
    source_type: str
    jurisdiction: str | None = None
    status: str = "draft"
    is_published: bool = False
    effective_from: date | None = None
    effective_to: date | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    storage_path: str | None = None
    content_text: str | None = None
    summary: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class NormativeSourceCreate(NormativeSourceBase):
    pass


class NormativeSourceUpdate(BaseModel):
    version: int | None = None
    title: str | None = None
    source_type: str | None = None
    jurisdiction: str | None = None
    status: str | None = None
    is_published: bool | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    storage_path: str | None = None
    content_text: str | None = None
    summary: str | None = None
    metadata_json: dict[str, Any] | None = None


class NormativeSourceRead(ORMModel, NormativeSourceBase):
    id: str
    created_at: datetime
    updated_at: datetime


class RetrievalResult(BaseModel):
    project_key: str
    source_id: str
    source_key: str
    source_version: int
    source_title: str
    source_type: str
    status: str
    effective_from: str | None = None
    effective_to: str | None = None
    chunk_id: str
    chunk_index: int
    text: str
    page_start: int | None = None
    page_end: int | None = None
    score: float


class RetrievalResponse(BaseModel):
    query: str
    count: int
    results: list[RetrievalResult] = Field(default_factory=list)


class AuditEventRead(ORMModel):
    id: str
    project_key: str
    entity_type: str
    entity_id: str
    action: str
    actor: str
    snapshot_json: dict[str, Any]
    created_at: datetime
