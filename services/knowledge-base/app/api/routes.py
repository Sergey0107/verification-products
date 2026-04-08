from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppealClassificationRule,
    AuditEvent,
    CanonicalAttribute,
    LetterTemplate,
    NormativeSource,
)
from app.db.session import get_db
from app.schemas import (
    AppealClassificationRuleCreate,
    AppealClassificationRuleRead,
    AppealClassificationRuleUpdate,
    AuditEventRead,
    CanonicalAttributeCreate,
    CanonicalAttributeRead,
    CanonicalAttributeUpdate,
    LetterTemplateCreate,
    LetterTemplateRead,
    LetterTemplateUpdate,
    NormativeSourceCreate,
    NormativeSourceRead,
    NormativeSourceUpdate,
    RetrievalResponse,
)
from app.services.audit import record_audit_event
from app.services.ingestion import ingest_normative_document, reindex_source_chunks
from app.services.retrieval import search_chunks

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PROJECTS = {
    "recalculation": {
        "title": "Перерасчеты и обращения",
        "description": "Шаблоны писем, правила классификации и нормативные документы для обращений граждан и запросов органов.",
        "accent": "teal",
    },
    "technical_compliance": {
        "title": "Сопоставление ТЗ и паспортов",
        "description": "Канонические характеристики, технические документы и правила для проверки соответствия оборудования.",
        "accent": "amber",
    },
}


def _project_or_404(project_key: str) -> dict[str, str]:
    project = PROJECTS.get(project_key)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _admin_url(project_key: str) -> str:
    return f"/admin/{project_key}"


def _apply_updates(model: Any, payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        setattr(model, key, value)


def _audit_snapshot(model: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for column in model.__table__.columns:  # type: ignore[attr-defined]
        value = getattr(model, column.name)
        if isinstance(value, date):
            data[column.name] = value.isoformat()
        else:
            data[column.name] = value
    return data


@router.get("/letter-templates", response_model=list[LetterTemplateRead])
def list_letter_templates(
    template_key: str | None = None,
    project_key: str | None = None,
    published_only: bool = True,
    db: Session = Depends(get_db),
):
    query = select(LetterTemplate)
    if project_key:
        query = query.where(LetterTemplate.project_key == project_key)
    if template_key:
        query = query.where(LetterTemplate.template_key == template_key)
    if published_only:
        query = query.where(LetterTemplate.is_published.is_(True))
    query = query.order_by(LetterTemplate.template_key, desc(LetterTemplate.version))
    return list(db.scalars(query))


@router.get("/letter-templates/resolve/{template_key}", response_model=LetterTemplateRead)
def resolve_letter_template(
    template_key: str,
    project_key: str = Query(default="recalculation"),
    db: Session = Depends(get_db),
):
    query = (
        select(LetterTemplate)
        .where(
            LetterTemplate.project_key == project_key,
            LetterTemplate.template_key == template_key,
            LetterTemplate.is_active.is_(True),
            LetterTemplate.is_published.is_(True),
        )
        .order_by(desc(LetterTemplate.version))
    )
    template = db.scalars(query).first()
    if template is None:
        raise HTTPException(status_code=404, detail="Letter template not found")
    return template


@router.post(
    "/admin/letter-templates",
    response_model=LetterTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_letter_template(payload: LetterTemplateCreate, db: Session = Depends(get_db)):
    template = LetterTemplate(**payload.model_dump(), is_system=False)
    db.add(template)
    db.flush()
    record_audit_event(
        db,
        project_key=template.project_key,
        entity_type="letter_template",
        entity_id=template.id,
        action="create",
        snapshot=payload.model_dump(),
    )
    db.commit()
    db.refresh(template)
    return template


@router.patch("/admin/letter-templates/{template_id}", response_model=LetterTemplateRead)
def update_letter_template(
    template_id: str,
    payload: LetterTemplateUpdate,
    db: Session = Depends(get_db),
):
    template = db.get(LetterTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Letter template not found")
    _apply_updates(template, payload.model_dump(exclude_unset=True))
    record_audit_event(
        db,
        entity_type="letter_template",
        entity_id=template.id,
        action="update",
        snapshot=_audit_snapshot(template),
    )
    db.commit()
    db.refresh(template)
    return template


@router.get("/appeal-classification-rules", response_model=list[AppealClassificationRuleRead])
def list_appeal_classification_rules(
    appeal_class: str | None = None,
    project_key: str | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    query = select(AppealClassificationRule)
    if project_key:
        query = query.where(AppealClassificationRule.project_key == project_key)
    if appeal_class:
        query = query.where(AppealClassificationRule.appeal_class == appeal_class)
    if active_only:
        query = query.where(AppealClassificationRule.is_active.is_(True))
    query = query.order_by(AppealClassificationRule.priority, AppealClassificationRule.rule_name)
    return list(db.scalars(query))


@router.post(
    "/admin/appeal-classification-rules",
    response_model=AppealClassificationRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_appeal_classification_rule(
    payload: AppealClassificationRuleCreate,
    db: Session = Depends(get_db),
):
    rule = AppealClassificationRule(**payload.model_dump(), is_system=False)
    db.add(rule)
    db.flush()
    record_audit_event(
        db,
        project_key=rule.project_key,
        entity_type="classification_rule",
        entity_id=rule.id,
        action="create",
        snapshot=payload.model_dump(),
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.patch(
    "/admin/appeal-classification-rules/{rule_id}",
    response_model=AppealClassificationRuleRead,
)
def update_appeal_classification_rule(
    rule_id: str,
    payload: AppealClassificationRuleUpdate,
    db: Session = Depends(get_db),
):
    rule = db.get(AppealClassificationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Appeal classification rule not found")
    _apply_updates(rule, payload.model_dump(exclude_unset=True))
    record_audit_event(
        db,
        project_key=rule.project_key,
        entity_type="classification_rule",
        entity_id=rule.id,
        action="update",
        snapshot=_audit_snapshot(rule),
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/canonical-attributes", response_model=list[CanonicalAttributeRead])
def list_canonical_attributes(
    domain: str | None = Query(default=None),
    project_key: str | None = Query(default=None),
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    query = select(CanonicalAttribute)
    effective_domain = domain or project_key
    if effective_domain:
        query = query.where(CanonicalAttribute.domain == effective_domain)
    if active_only:
        query = query.where(CanonicalAttribute.is_active.is_(True))
    query = query.order_by(CanonicalAttribute.domain, CanonicalAttribute.normalized_name)
    return list(db.scalars(query))


@router.post(
    "/admin/canonical-attributes",
    response_model=CanonicalAttributeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_canonical_attribute(
    payload: CanonicalAttributeCreate,
    db: Session = Depends(get_db),
):
    item = CanonicalAttribute(**payload.model_dump())
    db.add(item)
    db.flush()
    record_audit_event(
        db,
        project_key=item.domain,
        entity_type="canonical_attribute",
        entity_id=item.id,
        action="create",
        snapshot=payload.model_dump(),
    )
    db.commit()
    db.refresh(item)
    return item


@router.patch("/admin/canonical-attributes/{attribute_id}", response_model=CanonicalAttributeRead)
def update_canonical_attribute(
    attribute_id: str,
    payload: CanonicalAttributeUpdate,
    db: Session = Depends(get_db),
):
    item = db.get(CanonicalAttribute, attribute_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Canonical attribute not found")
    _apply_updates(item, payload.model_dump(exclude_unset=True))
    record_audit_event(
        db,
        project_key=item.domain,
        entity_type="canonical_attribute",
        entity_id=item.id,
        action="update",
        snapshot=_audit_snapshot(item),
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/normative-sources", response_model=list[NormativeSourceRead])
def list_normative_sources(
    project_key: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    query = select(NormativeSource)
    if project_key:
        query = query.where(NormativeSource.project_key == project_key)
    if status_filter:
        query = query.where(NormativeSource.status == status_filter)
    query = query.order_by(NormativeSource.source_key, desc(NormativeSource.version))
    return list(db.scalars(query))


@router.post(
    "/admin/normative-sources",
    response_model=NormativeSourceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_normative_source(payload: NormativeSourceCreate, db: Session = Depends(get_db)):
    item = NormativeSource(**payload.model_dump())
    db.add(item)
    db.flush()
    record_audit_event(
        db,
        project_key=item.project_key,
        entity_type="normative_source",
        entity_id=item.id,
        action="create",
        snapshot=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(item)
    return item


@router.patch("/admin/normative-sources/{source_id}", response_model=NormativeSourceRead)
def update_normative_source(
    source_id: str,
    payload: NormativeSourceUpdate,
    db: Session = Depends(get_db),
):
    item = db.get(NormativeSource, source_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Normative source not found")
    _apply_updates(item, payload.model_dump(exclude_unset=True))
    record_audit_event(
        db,
        project_key=item.project_key,
        entity_type="normative_source",
        entity_id=item.id,
        action="update",
        snapshot=_audit_snapshot(item),
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/retrieval/search", response_model=RetrievalResponse)
def retrieval_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=5, ge=1, le=20),
    project_key: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    effective_on: date | None = Query(default=None),
    published_only: bool = True,
    db: Session = Depends(get_db),
):
    results = search_chunks(
        db,
        query=q,
        limit=limit,
        project_key=project_key,
        source_type=source_type,
        effective_on=effective_on,
        published_only=published_only,
    )
    return RetrievalResponse(query=q, count=len(results), results=results)


@router.get("/audit-events", response_model=list[AuditEventRead])
def list_audit_events(
    project_key: str | None = None,
    entity_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = select(AuditEvent)
    if project_key:
        query = query.where(AuditEvent.project_key == project_key)
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    query = query.order_by(desc(AuditEvent.created_at)).limit(limit)
    return list(db.scalars(query))


@router.get("/admin", response_class=HTMLResponse)
def admin_redirect():
    return RedirectResponse(url=_admin_url("recalculation"), status_code=303)


@router.get("/admin/{project_key}", response_class=HTMLResponse)
def admin_page(
    request: Request,
    project_key: str,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_key)
    search_results = (
        search_chunks(db, query=q, limit=8, project_key=project_key, published_only=False) if q else []
    )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "request": request,
            "project_key": project_key,
            "project": project,
            "projects": PROJECTS,
            "q": q or "",
            "search_results": search_results,
            "sources": list(
                db.scalars(
                    select(NormativeSource)
                    .where(NormativeSource.project_key == project_key)
                    .order_by(NormativeSource.source_key, desc(NormativeSource.version))
                )
            ),
            "templates": list(
                db.scalars(
                    select(LetterTemplate)
                    .where(LetterTemplate.project_key == project_key)
                    .order_by(LetterTemplate.template_key, desc(LetterTemplate.version))
                )
            ),
            "rules": list(
                db.scalars(
                    select(AppealClassificationRule)
                    .where(AppealClassificationRule.project_key == project_key)
                    .order_by(AppealClassificationRule.priority, AppealClassificationRule.rule_name)
                )
            ),
            "attributes": list(
                db.scalars(
                    select(CanonicalAttribute)
                    .where(CanonicalAttribute.domain == project_key)
                    .order_by(CanonicalAttribute.domain, CanonicalAttribute.normalized_name)
                )
            ),
            "audit_events": list(
                db.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.project_key.in_([project_key, "shared"]))
                    .order_by(desc(AuditEvent.created_at))
                    .limit(30)
                )
            ),
        },
    )


@router.post("/admin/forms/normative-upload")
async def normative_upload_form(
    project_key: str = Form(...),
    source_key: str = Form(...),
    title: str = Form(...),
    source_type: str = Form(...),
    jurisdiction: str | None = Form(default=None),
    status_value: str = Form(default="draft"),
    effective_from: date | None = Form(default=None),
    effective_to: date | None = Form(default=None),
    summary: str | None = Form(default=None),
    metadata_json: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    raw_metadata = {}
    if metadata_json:
        try:
            raw_metadata = json.loads(metadata_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid metadata_json: {exc}") from exc

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty upload")

    ingest_normative_document(
        db,
        project_key=project_key.strip(),
        source_key=source_key.strip(),
        title=title.strip(),
        source_type=source_type.strip(),
        jurisdiction=(jurisdiction or "").strip() or None,
        status=status_value.strip(),
        effective_from=effective_from,
        effective_to=effective_to,
        summary=(summary or "").strip() or None,
        metadata_json=raw_metadata,
        file_name=file.filename or "document.txt",
        file_bytes=payload,
    )
    db.commit()
    return RedirectResponse(url=_admin_url(project_key.strip()), status_code=303)


@router.post("/admin/forms/letter-template")
def letter_template_form(
    project_key: str = Form(default="recalculation"),
    template_key: str = Form(...),
    version: int = Form(default=1),
    subject_template: str = Form(...),
    paragraphs_text: str = Form(...),
    variables_text: str = Form(default=""),
    is_active: bool = Form(default=True),
    is_published: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    payload = LetterTemplateCreate(
        project_key=project_key.strip(),
        template_key=template_key.strip(),
        version=version,
        subject_template=subject_template,
        paragraphs=[line.strip() for line in paragraphs_text.splitlines() if line.strip()],
        variables=[line.strip() for line in variables_text.splitlines() if line.strip()],
        is_active=is_active,
        is_published=is_published,
    )
    create_letter_template(payload, db)
    return RedirectResponse(url=_admin_url(project_key.strip()), status_code=303)


@router.post("/admin/forms/classification-rule")
def classification_rule_form(
    project_key: str = Form(default="recalculation"),
    appeal_class: str = Form(...),
    rule_name: str = Form(...),
    requester_type: str | None = Form(default=None),
    authority_type: str | None = Form(default=None),
    priority: int = Form(default=100),
    version: int = Form(default=1),
    description: str | None = Form(default=None),
    match_terms_text: str = Form(default=""),
    is_active: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    payload = AppealClassificationRuleCreate(
        project_key=project_key.strip(),
        appeal_class=appeal_class.strip(),
        rule_name=rule_name.strip(),
        requester_type=(requester_type or "").strip() or None,
        authority_type=(authority_type or "").strip() or None,
        priority=priority,
        version=version,
        description=(description or "").strip() or None,
        match_terms=[line.strip() for line in match_terms_text.splitlines() if line.strip()],
        is_active=is_active,
    )
    create_appeal_classification_rule(payload, db)
    return RedirectResponse(url=_admin_url(project_key.strip()), status_code=303)


@router.post("/admin/forms/canonical-attribute")
def canonical_attribute_form(
    project_key: str = Form(default="technical_compliance"),
    name: str = Form(...),
    normalized_name: str = Form(...),
    unit: str | None = Form(default=None),
    value_type: str = Form(default="string"),
    synonyms_text: str = Form(default=""),
    is_active: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    payload = CanonicalAttributeCreate(
        domain=project_key.strip(),
        name=name.strip(),
        normalized_name=normalized_name.strip(),
        unit=(unit or "").strip() or None,
        value_type=value_type.strip(),
        synonyms=[line.strip() for line in synonyms_text.splitlines() if line.strip()],
        is_active=is_active,
    )
    create_canonical_attribute(payload, db)
    return RedirectResponse(url=_admin_url(project_key.strip()), status_code=303)


@router.post("/admin/forms/source-status/{source_id}")
def source_status_form(
    source_id: str,
    project_key: str = Form(...),
    status_value: str = Form(...),
    db: Session = Depends(get_db),
):
    source = db.get(NormativeSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Normative source not found")
    source.status = status_value
    source.is_published = status_value == "published"
    reindex_source_chunks(db, source)
    record_audit_event(
        db,
        project_key=source.project_key,
        entity_type="normative_source",
        entity_id=source.id,
        action="status_change",
        snapshot={"status": source.status, "is_published": source.is_published},
    )
    db.commit()
    return RedirectResponse(url=_admin_url(project_key.strip()), status_code=303)
