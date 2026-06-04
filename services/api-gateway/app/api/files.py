from datetime import datetime
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.api.auth import get_current_user
from app.api.deps import parse_uuid
from app.core.config import settings
from app.db.models.analysis import Analysis
from app.db.models.files import File as FileModel
from app.db.models.users import User
from app.db.models.extraction_jobs import ExtractionJob
from app.db.session import get_db
from app.services.extraction_backends import normalize_extraction_backend
from app.tasks import extract_file

router = APIRouter()


@router.post("/files/upload")
async def upload_files(
    extraction_backend: str = Form("openrouter"),
    task_id: str = Form(""),
    product_model: str = Form(""),
    tz_file: UploadFile = File(...),
    passport_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    selected_backend = normalize_extraction_backend(extraction_backend)
    analysis = Analysis(
        user_id=current_user.id,
        status="processing_files",
        extraction_backend=selected_backend,
        task_id=task_id.strip() or None,
        product_model=product_model.strip() or None,
    )
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
        await tz_file.seek(0)
        await passport_file.seek(0)
        files = {
            "tz_file": (tz_file.filename, tz_file.file, tz_file.content_type),
            "passport_file": (
                passport_file.filename,
                passport_file.file,
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
            f"{settings.FILE_SERVICE_URL}/files/upload-batch", files=files, data=data
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
        select(Analysis.status, Analysis.extraction_backend, Analysis.product_model).where(Analysis.id == analysis_id)
    )
    analysis_state = status_before_result.one_or_none()
    status_before = analysis_state[0] if analysis_state else None
    extraction_backend = analysis_state[1] if analysis_state else "openrouter"
    product_model = analysis_state[2] if analysis_state else None

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
                FileModel.analysis_id == analysis_id,
                FileModel.status == "uploaded",
                FileModel.file_type == "tz",
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
                args=[
                    job_id,
                    analysis_id_value,
                    file_id,
                    file_type,
                    storage_path,
                    storage_url,
                    extraction_backend,
                    None,
                    product_model,
                ],
                task_id=job_id,
            )

    return {"ok": True}


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_uuid = parse_uuid(file_id)

    result = await db.execute(
        select(FileModel)
        .join(Analysis, Analysis.id == FileModel.analysis_id)
        .where(FileModel.id == file_uuid)
        .where(Analysis.user_id == current_user.id)
    )
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise HTTPException(status_code=404, detail="File not found")

    params = {"key": file_record.storage_path, "name": file_record.original_name}
    client = httpx.AsyncClient(timeout=60)
    resp = await client.get(f"{settings.FILE_SERVICE_URL}/files/download", params=params)
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


@router.get("/files/{file_id}/preview")
async def preview_file(
    file_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_uuid = parse_uuid(file_id)

    result = await db.execute(
        select(FileModel)
        .join(Analysis, Analysis.id == FileModel.analysis_id)
        .where(FileModel.id == file_uuid)
        .where(Analysis.user_id == current_user.id)
    )
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise HTTPException(status_code=404, detail="File not found")

    is_pdf = (file_record.mime_type or "").lower() == "application/pdf" or \
             (file_record.original_name or "").lower().endswith(".pdf")

    if is_pdf:
        # Для PDF: рендерим через extraction-service (PyMuPDF) чтобы решить проблему
        # с нестандартными кириллическими шрифтами, которые PDF.js не умеет отображать.
        # Получаем свежий presigned URL и передаём в /render-pdf.
        try:
            presign_client = httpx.AsyncClient(timeout=15)
            presign_resp = await presign_client.get(
                f"{settings.FILE_SERVICE_URL}/files/presign",
                params={"key": file_record.storage_path, "expires_in": 3600},
            )
            await presign_client.aclose()
            presign_resp.raise_for_status()
            presigned_url = presign_resp.json().get("url", "")
        except Exception:
            presigned_url = ""

        if presigned_url:
            client = httpx.AsyncClient(timeout=300)
            render_resp = await client.get(
                f"{settings.EXTRACTION_SERVICE_URL}/render-pdf",
                params={"url": presigned_url},
            )
            if render_resp.status_code == 200:
                async def _close_render():
                    await render_resp.aclose()
                    await client.aclose()
                background_tasks.add_task(_close_render)
                return StreamingResponse(
                    render_resp.aiter_bytes(),
                    media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=preview.pdf"},
                )
            await render_resp.aclose()
            await client.aclose()
        # Fallback: отдаём оригинальный PDF

    params = {
        "key": file_record.storage_path,
        "name": file_record.original_name,
    }
    if file_record.mime_type:
        params["content_type"] = file_record.mime_type

    client = httpx.AsyncClient(timeout=120)
    resp = await client.get(f"{settings.FILE_SERVICE_URL}/files/preview", params=params)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "application/pdf")
    content_disposition = resp.headers.get("content-disposition")
    headers = {}
    if content_disposition:
        headers["content-disposition"] = content_disposition

    async def _close():
        await resp.aclose()
        await client.aclose()

    background_tasks.add_task(_close)
    return StreamingResponse(resp.aiter_bytes(), media_type=content_type, headers=headers)
