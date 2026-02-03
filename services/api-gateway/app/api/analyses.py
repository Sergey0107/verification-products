from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.analysis import Analysis
from app.db.models.extraction_results import ExtractionResult
from app.db.models.comparison_jobs import ComparisonJob
from app.db.models.files import File as FileModel
from app.db.session import get_db

router = APIRouter()


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
        select(Analysis.id, Analysis.status, Analysis.created_at).order_by(
            Analysis.created_at.desc()
        )
    )
    analyses = rows.all()
    items = []
    for analysis_id, status, created_at in analyses:
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
                "created_at": created_at.isoformat() if created_at else None,
            }
        )
    return items


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
