from datetime import datetime
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.db.models.analysis import Analysis
from app.db.models.files import File as FileModel
from app.db.models.extraction_jobs import ExtractionJob
from app.db.session import get_db
from app.tasks import extract_file

router = APIRouter()


@router.post("/files/upload")
async def upload_files(
    tz_file: UploadFile = File(...),
    passport_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    analysis = Analysis(status="processing_files")
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)

    tz_key = f"tz/{uuid4()}_{tz_file.filename}"
    passport_key = f"passport/{uuid4()}_{passport_file.filename}"

    tz_record = FileModel(
        analysis_id=analysis.id,
        file_type="tz",
        original_name=tz_file.filename or "",
        storage_path=tz_key,
        status="uploading",
    )
    passport_record = FileModel(
        analysis_id=analysis.id,
        file_type="passport",
        original_name=passport_file.filename or "",
        storage_path=passport_key,
        status="uploading",
    )
    db.add_all([tz_record, passport_record])
    await db.flush()
    await db.refresh(tz_record)
    await db.refresh(passport_record)
    await db.commit()

    async with httpx.AsyncClient() as client:
        files = {
            "tz_file": (tz_file.filename, await tz_file.read(), tz_file.content_type),
            "passport_file": (
                passport_file.filename,
                await passport_file.read(),
                passport_file.content_type,
            ),
        }
        data = {
            "analysis_id": str(analysis.id),
            "tz_file_id": str(tz_record.id),
            "passport_file_id": str(passport_record.id),
            "tz_key": tz_key,
            "passport_key": passport_key,
        }
        response = await client.post(
            "http://file-service:8000/files/upload-batch", files=files, data=data
        )
        response.raise_for_status()
        return response.json()


@router.post("/files/callback")
async def files_callback(payload: dict, db: AsyncSession = Depends(get_db)):
    try:
        file_id = UUID(payload.get("file_id"))
        analysis_id = UUID(payload.get("analysis_id"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ids")

    status_value = payload.get("status")
    if status_value not in {"uploaded", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    values = {"status": status_value}
    if status_value == "uploaded":
        values.update(
            {
                "storage_path": payload.get("storage_path"),
                "storage_url": payload.get("url"),
                "mime_type": payload.get("mime_type"),
                "size_bytes": payload.get("size_bytes"),
                "uploaded_at": datetime.utcnow(),
            }
        )

    status_before_result = await db.execute(
        select(Analysis.status).where(Analysis.id == analysis_id)
    )
    status_before = status_before_result.scalar_one_or_none()

    await db.execute(
        update(FileModel)
        .where(FileModel.id == file_id)
        .where(FileModel.analysis_id == analysis_id)
        .values(**values)
    )
    await db.commit()

    if status_value == "failed":
        await db.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(status="failed", updated_at=datetime.utcnow())
        )
        await db.commit()
        return {"ok": True}

    result = await db.execute(
        select(func.count(FileModel.id)).where(
            FileModel.analysis_id == analysis_id, FileModel.status == "uploaded"
        )
    )
    uploaded_count = result.scalar_one() or 0
    if uploaded_count >= 2 and status_before != "files_uploaded":
        await db.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(status="extracting_data", updated_at=datetime.utcnow())
        )
        files_result = await db.execute(
            select(FileModel).where(
                FileModel.analysis_id == analysis_id, FileModel.status == "uploaded"
            )
        )
        new_jobs = []
        for file_record in files_result.scalars().all():
            stmt = (
                insert(ExtractionJob)
                .values(
                    analysis_id=analysis_id,
                    file_id=file_record.id,
                    file_type=file_record.file_type,
                    status="queued",
                )
                .on_conflict_do_nothing(
                    index_elements=["analysis_id", "file_id", "file_type"]
                )
                .returning(ExtractionJob.id)
            )
            result = await db.execute(stmt)
            job_id = result.scalar_one_or_none()
            if job_id:
                new_jobs.append(
                    (
                        str(job_id),
                        str(analysis_id),
                        str(file_record.id),
                        file_record.file_type,
                        file_record.storage_path,
                        file_record.storage_url,
                    )
                )
        await db.commit()
        for job_id, analysis_id_value, file_id, file_type, storage_path, storage_url in new_jobs:
            extract_file.apply_async(
                args=[job_id, analysis_id_value, file_id, file_type, storage_path, storage_url],
                task_id=job_id,
            )

    return {"ok": True}


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)
):
    try:
        file_uuid = UUID(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    result = await db.execute(select(FileModel).where(FileModel.id == file_uuid))
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise HTTPException(status_code=404, detail="File not found")

    params = {"key": file_record.storage_path, "name": file_record.original_name}
    client = httpx.AsyncClient(timeout=60)
    resp = await client.get("http://file-service:8000/files/download", params=params)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "application/octet-stream")
    content_disposition = resp.headers.get("content-disposition")
    headers = {}
    if content_disposition:
        headers["content-disposition"] = content_disposition

    async def _close():
        await resp.aclose()
        await client.aclose()

    background_tasks.add_task(_close)
    return StreamingResponse(resp.aiter_bytes(), media_type=content_type, headers=headers)
