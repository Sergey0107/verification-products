from datetime import datetime
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.analysis import Analysis
from app.db.models.extraction_results import ExtractionResult
from app.db.models.comparison_jobs import ComparisonJob
from app.db.models.files import File as FileModel
from app.db.models.analysis import ComparisonRow
from app.db.session import get_db
from app.services.extraction_backends import extraction_backend_label

router = APIRouter()


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
            evidence = _build_characteristic_evidence(
                file_type,
                references if isinstance(references, list) else [],
                value_text or None,
            )
            items.append(
                {
                    "characteristic_id": f"{file_type}-{product_index}-{characteristic_index}",
                    "product_name": product_name,
                    "name": name,
                    "label": f"{product_name} — {name}",
                    "value": value_text,
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
        "ready": "ready",
        "failed": "error",
    }
    return mapping.get(status, "in-progress")


async def build_analysis_items(db: AsyncSession) -> list[dict]:
    rows = await db.execute(
        select(
            Analysis.id,
            Analysis.status,
            Analysis.created_at,
            Analysis.extraction_backend,
        ).order_by(
            Analysis.created_at.desc()
        )
    )
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
                "llm_result": row.llm_result,
                "tz_evidence": row.tz_evidence
                or _fallback_evidence("tz", row.tz_quote, row.tz_value),
                "passport_evidence": row.passport_evidence
                or _fallback_evidence("passport", row.passport_quote, row.passport_value),
            }
            for row in rows
        ],
    }


@router.get("/analyses")
async def list_analyses(db: AsyncSession = Depends(get_db)):
    items = await build_analysis_items(db)
    return {"items": items}


@router.post("/analyses/{analysis_id}/status")
async def set_status(analysis_id: str, status: str, db: AsyncSession = Depends(get_db)):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    await db.execute(
        update(Analysis)
        .where(Analysis.id == analysis_uuid)
        .values(status=status, updated_at=datetime.utcnow())
    )
    await db.commit()
    return {"ok": True}


@router.get("/analyses/{analysis_id}/extraction/{file_type}")
async def get_extraction(
    analysis_id: str, file_type: str, db: AsyncSession = Depends(get_db)
):
    if file_type not in {"tz", "passport"}:
        raise HTTPException(status_code=400, detail="Invalid file type")
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
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
async def get_comparison(analysis_id: str, db: AsyncSession = Depends(get_db)):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    result = await db.execute(
        select(ComparisonJob).where(ComparisonJob.analysis_id == analysis_uuid)
    )
    job = result.scalar_one_or_none()
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(content=job.result)


@router.get("/analyses/{analysis_id}/viewer-context")
async def get_viewer_context(analysis_id: str, db: AsyncSession = Depends(get_db)):
    try:
        analysis_uuid = UUID(analysis_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    return await build_viewer_context_payload(analysis_uuid, db)
