from datetime import datetime
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.models.analysis import Analysis, TzCharacteristicReview
from app.db.models.extraction_results import ExtractionResult
from app.db.models.comparison_jobs import ComparisonJob
from app.db.models.extraction_jobs import ExtractionJob
from app.db.models.files import File as FileModel
from app.db.models.analysis import ComparisonRow
from app.db.models.users import User
from app.db.session import get_db
from app.services.extraction_backends import extraction_backend_label
from app.tasks import extract_file

router = APIRouter()


class TzReviewDecision(BaseModel):
    characteristic_id: str
    approved: bool


class TzReviewSaveRequest(BaseModel):
    items: list[TzReviewDecision] = Field(default_factory=list)


def _extract_page_number(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(?:стр\.?|страниц[аеы]?|с\.?|page|p\.)\s*(\d{1,4})", text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        page = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _fallback_evidence(document_type: str, quote: str | None, value: str | None) -> dict:
    display_quote = quote or value
    source_spans = []
    if display_quote:
        source_spans.append(
            {
                "fragment_type": "page_anchor" if _extract_page_number(display_quote) else "fallback_quote",
                "locator_strategy": "page_anchor" if _extract_page_number(display_quote) else "fallback_quote",
                "page_number": _extract_page_number(display_quote),
                "page": _extract_page_number(display_quote),
                "anchor_text": display_quote,
                "quote_text": quote,
                "locator_text": display_quote,
                "bbox": None,
                "confidence": 0.35 if quote else 0.2,
            }
        )
    navigation_target = source_spans[0] if source_spans else None
    return {
        "evidence_version": "v2",
        "document_type": document_type,
        "position_status": "page_anchor" if navigation_target and navigation_target.get("page_number") else "text_anchor" if navigation_target else "missing",
        "locator_strategy": navigation_target.get("locator_strategy") if navigation_target else "missing",
        "display_quote": display_quote,
        "full_quote": display_quote,
        "fallback_quote": display_quote,
        "quote_origin": "legacy_quote" if quote else "legacy_value" if value else "missing",
        "matched_terms": [display_quote] if display_quote else [],
        "confidence": navigation_target.get("confidence") if navigation_target else 0.0,
        "source_spans": source_spans,
        "page_anchors": (
            [{"page_number": navigation_target["page_number"], "page": navigation_target["page_number"], "label": f"Страница {navigation_target['page_number']}"}]
            if navigation_target and navigation_target.get("page_number")
            else []
        ),
        "active_span": navigation_target,
        "exact_span": None,
        "text_anchor": navigation_target if navigation_target and not navigation_target.get("page_number") else None,
        "page_anchor": navigation_target if navigation_target and navigation_target.get("page_number") else None,
        "navigation_target": navigation_target,
    }


def _extract_products_from_payload(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    root = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(root, dict):
        return []
    if isinstance(root.get("products"), list):
        return [item for item in root.get("products", []) if isinstance(item, dict)]
    extraction = root.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("products"), list):
        return [item for item in extraction.get("products", []) if isinstance(item, dict)]
    return []


def _reference_to_span(reference: object, fallback_text: str | None) -> dict | None:
    if isinstance(reference, dict):
        page = reference.get("page")
        if isinstance(page, str) and page.isdigit():
            page = int(page)
        if not isinstance(page, int) or page <= 0:
            page = _extract_page_number(
                str(reference.get("quote_text") or reference.get("anchor_text") or reference.get("locator_text") or "")
            )
        return {
            "fragment_type": "page_anchor" if page else "text_anchor",
            "locator_strategy": str(reference.get("locator_strategy") or ("page_anchor" if page else "text_anchor")),
            "page_number": page,
            "page": page,
            "anchor_text": reference.get("anchor_text") or reference.get("locator_text") or fallback_text,
            "quote_text": reference.get("quote_text") or fallback_text,
            "locator_text": reference.get("locator_text") or reference.get("anchor_text") or fallback_text,
            "bbox": reference.get("bbox") if isinstance(reference.get("bbox"), dict) else None,
            "confidence": reference.get("confidence") if isinstance(reference.get("confidence"), (int, float)) else None,
        }
    if isinstance(reference, str):
        page = _extract_page_number(reference)
        return {
            "fragment_type": "page_anchor" if page else "text_anchor",
            "locator_strategy": "page_anchor" if page else "text_anchor",
            "page_number": page,
            "page": page,
            "anchor_text": reference,
            "quote_text": fallback_text or reference,
            "locator_text": reference,
            "bbox": None,
            "confidence": None,
        }
    return None


def _build_characteristic_evidence(file_type: str, references: list[object], value: str | None) -> dict:
    spans = []
    for reference in references:
        span = _reference_to_span(reference, value)
        if span:
            spans.append(span)
    if not spans and value:
        spans.append(
            {
                "fragment_type": "fallback_quote",
                "locator_strategy": "fallback_quote",
                "page_number": None,
                "page": None,
                "anchor_text": value,
                "quote_text": value,
                "locator_text": value,
                "bbox": None,
                "confidence": None,
            }
        )
    active_span = spans[0] if spans else None
    return {
        "evidence_version": "v2",
        "document_type": file_type,
        "position_status": "page_anchor" if active_span and active_span.get("page_number") else "text_anchor" if active_span else "missing",
        "locator_strategy": active_span.get("locator_strategy") if active_span else "missing",
        "display_quote": active_span.get("quote_text") if active_span else value,
        "full_quote": active_span.get("quote_text") if active_span else value,
        "fallback_quote": value,
        "quote_origin": "extraction_reference" if spans else "fallback_value",
        "matched_terms": [value] if value else [],
        "confidence": active_span.get("confidence") if active_span else None,
        "source_spans": spans,
        "page_anchors": [
            {"page_number": span["page_number"], "page": span["page_number"], "label": f"Страница {span['page_number']}"}
            for span in spans
            if span.get("page_number")
        ],
        "active_span": active_span,
        "exact_span": next((span for span in spans if span.get("bbox")), None),
        "text_anchor": next((span for span in spans if span.get("fragment_type") == "text_anchor"), None),
        "page_anchor": next((span for span in spans if span.get("page_number")), None),
        "navigation_target": active_span,
    }


def _build_document_characteristics(file_type: str, payload: dict | None) -> list[dict]:
    products = _extract_products_from_payload(payload)
    items: list[dict] = []
    for product_index, product in enumerate(products):
        product_name = str(product.get("product_name") or "Неизвестное изделие")
        characteristics = product.get("characteristics")
        if not isinstance(characteristics, list):
            continue
        for characteristic_index, characteristic in enumerate(characteristics):
            if not isinstance(characteristic, dict):
                continue
            name = str(characteristic.get("name") or "").strip()
            if not name:
                continue
            value = characteristic.get("value")
            value_text = str(value) if value is not None else ""
            references = characteristic.get("references")
            references_list = references if isinstance(references, list) else []
            evidence = _build_characteristic_evidence(
                file_type,
                references_list,
                value_text or None,
            )
            items.append(
                {
                    "characteristic_id": f"{file_type}-{product_index}-{characteristic_index}",
                    "product_name": product_name,
                    "name": name,
                    "label": f"{product_name} — {name}",
                    "value": value_text,
                    "references": references_list,
                    "evidence": evidence,
                }
            )
    return items


def _status_label(status: str) -> str:
    mapping = {
        "processing_files": "обработка файлов",
        "files_uploaded": "файл загружен",
        "extracting_data": "извлечение данных",
        "analyzing_data": "анализ данных",
        "extracting_passport": "извлечение паспорта",
        "tz_review": "проверка ТЗ",
        "ready": "готово",
        "failed": "ошибка",
    }
    return mapping.get(status, status)


def _status_key(status: str) -> str:
    mapping = {
        "processing_files": "in-progress",
        "files_uploaded": "in-progress",
        "extracting_data": "in-progress",
        "analyzing_data": "in-progress",
        "extracting_passport": "in-progress",
        "tz_review": "review",
        "ready": "ready",
        "failed": "error",
    }
    return mapping.get(status, "in-progress")


def _truncate_error(value: str | None, limit: int = 700) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _classify_error(value: str | None) -> str | None:
    if not value:
        return None
    lower = value.lower()
    if "openrouter" in lower and "429" in lower:
        return "Лимит или баланс OpenRouter"
    if "rate limit" in lower or "too many requests" in lower:
        return "Лимит запросов провайдера"
    if "insufficient" in lower and ("credit" in lower or "fund" in lower):
        return "Недостаточно средств OpenRouter"
    if "docx conversion failed" in lower or "is not a word file" in lower:
        return "Неверный формат Word-файла"
    if "invalid json" in lower or "jsondecodeerror" in lower or "unterminated string" in lower:
        return "Некорректный JSON от модели"
    if "failed to download file" in lower:
        return "Не удалось скачать файл"
    if "timeout" in lower or "timed out" in lower:
        return "Таймаут внешнего сервиса"
    if "openrouter" in lower:
        return "Ошибка OpenRouter"
    return "Ошибка обработки"


def _build_error_payload(prefix: str, detail: str | None) -> tuple[str | None, str | None]:
    if not detail:
        return None, None
    summary = _classify_error(detail)
    full_detail = f"{prefix}: {detail}"
    return summary, full_detail


async def build_analysis_items(db: AsyncSession, user: User | None = None) -> list[dict]:
    query = select(
        Analysis.id,
        Analysis.status,
        Analysis.created_at,
        Analysis.extraction_backend,
    )
    if user is not None:
        query = query.where(Analysis.user_id == user.id)
    rows = await db.execute(query.order_by(Analysis.created_at.desc()))
    analyses = rows.all()
    items = []
    for analysis_id, status, created_at, extraction_backend in analyses:
        files_rows = await db.execute(
            select(
                FileModel.id,
                FileModel.file_type,
                FileModel.original_name,
                FileModel.status,
            ).where(FileModel.analysis_id == analysis_id)
        )
        files = files_rows.all()
        tz = next((f for f in files if f.file_type == "tz"), None)
        passport = next((f for f in files if f.file_type == "passport"), None)
        error_summary = None
        error_detail = None
        if status == "failed":
            extraction_error_rows = await db.execute(
                select(ExtractionJob.file_type, ExtractionJob.last_error)
                .where(ExtractionJob.analysis_id == analysis_id)
                .where(ExtractionJob.last_error.is_not(None))
                .order_by(ExtractionJob.updated_at.desc())
            )
            extraction_error = extraction_error_rows.first()
            if extraction_error:
                file_label = "ТЗ" if extraction_error.file_type == "tz" else "паспорт"
                error_summary, error_detail = _build_error_payload(
                    f"Ошибка извлечения ({file_label})",
                    extraction_error.last_error,
                )
            else:
                comparison_error_rows = await db.execute(
                    select(ComparisonJob.last_error)
                    .where(ComparisonJob.analysis_id == analysis_id)
                    .where(ComparisonJob.last_error.is_not(None))
                    .order_by(ComparisonJob.updated_at.desc())
                )
                comparison_error = comparison_error_rows.scalar_one_or_none()
                error_summary, error_detail = _build_error_payload(
                    "Ошибка сравнения",
                    comparison_error,
                )

        items.append(
            {
                "analysis_id": str(analysis_id),
                "tz": tz.original_name if tz else "",
                "tz_id": str(tz.id) if tz else "",
                "passport": passport.original_name if passport else "",
                "passport_id": str(passport.id) if passport else "",
                "status": _status_label(status),
                "status_key": _status_key(status),
                "extraction_backend": extraction_backend,
                "extraction_backend_label": extraction_backend_label(extraction_backend),
                "created_at": created_at.isoformat() if created_at else None,
                "error_message": _truncate_error(error_detail),
                "error_summary": error_summary,
                "error_detail": error_detail,
            }
        )
    return items


async def build_viewer_context_payload(analysis_id: UUID, db: AsyncSession) -> dict:
    extraction_result_rows = await db.execute(
        select(ExtractionResult).where(ExtractionResult.analysis_id == analysis_id)
    )
    extraction_results = {
        row.file_type: row.payload for row in extraction_result_rows.scalars().all()
    }
    files_result = await db.execute(
        select(FileModel).where(FileModel.analysis_id == analysis_id)
    )
    file_rows = files_result.scalars().all()
    documents: dict[str, dict] = {}
    for file_row in file_rows:
        documents[file_row.file_type] = {
            "file_id": str(file_row.id),
            "file_name": file_row.original_name,
            "mime_type": file_row.mime_type,
            "download_url": f"/files/{file_row.id}/download",
            "viewer_url": f"/files/{file_row.id}/preview",
            "viewer_mime_type": "application/pdf",
            "characteristics": _build_document_characteristics(
                file_row.file_type,
                extraction_results.get(file_row.file_type),
            ),
        }

    rows_result = await db.execute(
        select(ComparisonRow).where(ComparisonRow.analysis_id == analysis_id)
    )
    rows = rows_result.scalars().all()
    return {
        "analysis_id": str(analysis_id),
        "evidence_version": "v2",
        "documents": documents,
        "available_documents": documents,
        "rows": [
            {
                "row_id": str(row.id),
                "characteristic": row.characteristic,
                "tz_value": row.tz_value,
                "passport_value": row.passport_value,
                "llm_result": row.llm_result,
                "tz_evidence": row.tz_evidence
                or _fallback_evidence("tz", row.tz_quote, row.tz_value),
                "passport_evidence": row.passport_evidence
                or _fallback_evidence("passport", row.passport_quote, row.passport_value),
            }
            for row in rows
        ],
    }


async def _ensure_analysis_owner(
    analysis_id: UUID,
    db: AsyncSession,
    user: User,
) -> Analysis:
    result = await db.execute(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .where(Analysis.user_id == user.id)
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


async def _get_tz_review_source(
    analysis_id: UUID,
    db: AsyncSession,
) -> tuple[ExtractionResult, FileModel]:
    extraction_result = await db.execute(
        select(ExtractionResult)
        .where(ExtractionResult.analysis_id == analysis_id)
        .where(ExtractionResult.file_type == "tz")
    )
    extraction_row = extraction_result.scalar_one_or_none()
    if extraction_row is None:
        raise HTTPException(status_code=409, detail="TZ extraction is not ready")

    file_result = await db.execute(
        select(FileModel)
        .where(FileModel.analysis_id == analysis_id)
        .where(FileModel.file_type == "tz")
    )
    file_row = file_result.scalar_one_or_none()
    if file_row is None:
        raise HTTPException(status_code=404, detail="TZ file not found")
    return extraction_row, file_row


async def _tz_review_rows_map(
    analysis_id: UUID,
    db: AsyncSession,
) -> dict[str, TzCharacteristicReview]:
    result = await db.execute(
        select(TzCharacteristicReview).where(TzCharacteristicReview.analysis_id == analysis_id)
    )
    return {row.characteristic_id: row for row in result.scalars().all()}


def _merge_tz_review_items(
    characteristics: list[dict],
    rows_by_id: dict[str, TzCharacteristicReview],
) -> list[dict]:
    items = []
    for item in characteristics:
        row = rows_by_id.get(item["characteristic_id"])
        merged = dict(item)
        merged["approved"] = bool(row.approved) if row else True
        items.append(merged)
    return items


async def _save_tz_review_decisions(
    analysis_id: UUID,
    characteristics: list[dict],
    decisions: dict[str, bool],
    db: AsyncSession,
) -> None:
    characteristic_ids = {item["characteristic_id"] for item in characteristics}
    unknown_ids = set(decisions) - characteristic_ids
    if unknown_ids:
        raise HTTPException(status_code=400, detail="Unknown TZ characteristic id")

    rows_by_id = await _tz_review_rows_map(analysis_id, db)
    now = datetime.utcnow()
    for item in characteristics:
        characteristic_id = item["characteristic_id"]
        existing = rows_by_id.get(characteristic_id)
        approved = decisions.get(
            characteristic_id,
            bool(existing.approved) if existing else True,
        )
        stmt = (
            insert(TzCharacteristicReview)
            .values(
                analysis_id=analysis_id,
                characteristic_id=characteristic_id,
                product_name=item["product_name"],
                name=item["name"],
                value=item.get("value") or None,
                references=item.get("references"),
                evidence=item.get("evidence"),
                approved=approved,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["analysis_id", "characteristic_id"],
                set_={
                    "product_name": item["product_name"],
                    "name": item["name"],
                    "value": item.get("value") or None,
                    "references": item.get("references"),
                    "evidence": item.get("evidence"),
                    "approved": approved,
                    "updated_at": now,
                },
            )
        )
        await db.execute(stmt)


def _review_target_characteristics(
    rows: list[TzCharacteristicReview],
    product_model: str | None = None,
) -> list[dict]:
    return [
        {
            "characteristic_id": row.characteristic_id,
            "product_name": row.product_name,
            "product_model": product_model,
            "name": row.name,
            "value": row.value,
        }
        for row in rows
    ]


@router.get("/analyses/{analysis_id}/tz-review")
async def get_tz_review(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    await _ensure_analysis_owner(analysis_uuid, db, current_user)
    extraction_row, file_row = await _get_tz_review_source(analysis_uuid, db)
    characteristics = _build_document_characteristics("tz", extraction_row.payload)
    rows_by_id = await _tz_review_rows_map(analysis_uuid, db)
    return {
        "analysis_id": str(analysis_uuid),
        "document": {
            "file_id": str(file_row.id),
            "file_name": file_row.original_name,
            "mime_type": file_row.mime_type,
            "download_url": f"/files/{file_row.id}/download",
            "viewer_url": f"/files/{file_row.id}/preview",
            "viewer_mime_type": "application/pdf",
        },
        "items": _merge_tz_review_items(characteristics, rows_by_id),
    }


@router.put("/analyses/{analysis_id}/tz-review")
async def save_tz_review(
    analysis_id: str,
    payload: TzReviewSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    await _ensure_analysis_owner(analysis_uuid, db, current_user)
    extraction_row, _ = await _get_tz_review_source(analysis_uuid, db)
    characteristics = _build_document_characteristics("tz", extraction_row.payload)
    decisions = {item.characteristic_id: item.approved for item in payload.items}
    await _save_tz_review_decisions(analysis_uuid, characteristics, decisions, db)
    await db.commit()
    rows_by_id = await _tz_review_rows_map(analysis_uuid, db)
    return {"ok": True, "items": _merge_tz_review_items(characteristics, rows_by_id)}


@router.post("/analyses/{analysis_id}/tz-review/continue")
async def continue_tz_review(
    analysis_id: str,
    payload: TzReviewSaveRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    analysis = await _ensure_analysis_owner(analysis_uuid, db, current_user)
    if analysis.status in {"ready", "analyzing_data", "extracting_passport"}:
        return {"ok": True, "status": analysis.status}

    extraction_row, _ = await _get_tz_review_source(analysis_uuid, db)
    characteristics = _build_document_characteristics("tz", extraction_row.payload)
    decisions = {
        item.characteristic_id: item.approved
        for item in (payload.items if payload else [])
    }
    await _save_tz_review_decisions(analysis_uuid, characteristics, decisions, db)

    approved_result = await db.execute(
        select(TzCharacteristicReview)
        .where(TzCharacteristicReview.analysis_id == analysis_uuid)
        .where(TzCharacteristicReview.approved.is_(True))
        .order_by(TzCharacteristicReview.created_at.asc())
    )
    approved_rows = approved_result.scalars().all()
    if not approved_rows:
        raise HTTPException(status_code=400, detail="At least one TZ characteristic must be approved")

    passport_result = await db.execute(
        select(FileModel)
        .where(FileModel.analysis_id == analysis_uuid)
        .where(FileModel.file_type == "passport")
    )
    passport_file = passport_result.scalar_one_or_none()
    if passport_file is None:
        raise HTTPException(status_code=404, detail="Passport file not found")
    if passport_file.status != "uploaded":
        raise HTTPException(status_code=409, detail="Passport file is not uploaded")

    await db.execute(
        update(Analysis)
        .where(Analysis.id == analysis_uuid)
        .values(status="extracting_passport", updated_at=datetime.utcnow())
    )
    create_job = (
        insert(ExtractionJob)
        .values(
            analysis_id=analysis_uuid,
            file_id=passport_file.id,
            file_type="passport",
            status="queued",
        )
        .on_conflict_do_nothing(index_elements=["analysis_id", "file_id", "file_type"])
        .returning(ExtractionJob.id)
    )
    job_result = await db.execute(create_job)
    job_id = job_result.scalar_one_or_none()
    should_enqueue = job_id is not None
    if job_id is None:
        existing_result = await db.execute(
            select(ExtractionJob)
            .where(ExtractionJob.analysis_id == analysis_uuid)
            .where(ExtractionJob.file_id == passport_file.id)
            .where(ExtractionJob.file_type == "passport")
        )
        existing_job = existing_result.scalar_one_or_none()
        if existing_job is None:
            raise HTTPException(status_code=500, detail="Failed to create passport extraction job")
        job_id = existing_job.id
        should_enqueue = existing_job.status == "failed"
        if should_enqueue:
            await db.execute(
                update(ExtractionJob)
                .where(ExtractionJob.id == existing_job.id)
                .values(
                    status="queued",
                    attempts=0,
                    last_error=None,
                    updated_at=datetime.utcnow(),
                    completed_at=None,
                )
            )

    # Достаём product_model из extraction result ТЗ чтобы передать в паспорт —
    # LLM будет знать какую именно модель искать в таблице паспорта
    tz_product_model: str | None = None
    try:
        tz_extraction_result = await db.execute(
            select(ExtractionResult)
            .where(ExtractionResult.analysis_id == analysis_uuid)
            .where(ExtractionResult.file_type == "tz")
        )
        tz_extraction = tz_extraction_result.scalar_one_or_none()
        if tz_extraction and tz_extraction.payload:
            products = tz_extraction.payload.get("extraction", {}).get("products", [])
            if products:
                tz_product_model = products[0].get("product_model")
    except Exception:
        pass

    await db.commit()
    if should_enqueue:
        extract_file.apply_async(
            args=[
                str(job_id),
                str(analysis_uuid),
                str(passport_file.id),
                "passport",
                passport_file.storage_path,
                passport_file.storage_url,
                analysis.extraction_backend,
                _review_target_characteristics(approved_rows, tz_product_model),
            ],
            task_id=str(job_id),
        )
    return {"ok": True, "status": "extracting_passport"}


@router.get("/analyses")
async def list_analyses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = await build_analysis_items(db, current_user)
    return {"items": items}


@router.post("/analyses/{analysis_id}/status")
async def set_status(
    analysis_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    await _ensure_analysis_owner(analysis_uuid, db, current_user)
    await db.execute(
        update(Analysis)
        .where(Analysis.id == analysis_uuid)
        .values(status=status, updated_at=datetime.utcnow())
    )
    await db.commit()
    return {"ok": True}


@router.get("/analyses/{analysis_id}/extraction/{file_type}")
async def get_extraction(
    analysis_id: str,
    file_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if file_type not in {"tz", "passport"}:
        raise HTTPException(status_code=400, detail="Invalid file type")
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    await _ensure_analysis_owner(analysis_uuid, db, current_user)
    result = await db.execute(
        select(ExtractionResult)
        .where(ExtractionResult.analysis_id == analysis_uuid)
        .where(ExtractionResult.file_type == file_type)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=row.payload)


@router.get("/analyses/{analysis_id}/comparison")
async def get_comparison(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    await _ensure_analysis_owner(analysis_uuid, db, current_user)
    result = await db.execute(
        select(ComparisonJob).where(ComparisonJob.analysis_id == analysis_uuid)
    )
    job = result.scalar_one_or_none()
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=job.result)


@router.get("/analyses/{analysis_id}/viewer-context")
async def get_viewer_context(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    await _ensure_analysis_owner(analysis_uuid, db, current_user)
    return await build_viewer_context_payload(analysis_uuid, db)
