from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from celery.result import AsyncResult

from app.celery_app import celery_app
from app.core.config import settings
from app.tasks import upload_to_s3

router = APIRouter()


@router.post("/files/upload-batch")
async def upload_batch(
    tz_file: UploadFile = File(...),
    passport_file: UploadFile = File(...),
    analysis_id: str = Form(...),
    tz_file_id: str = Form(...),
    passport_file_id: str = Form(...),
    tz_key: str = Form(...),
    passport_key: str = Form(...),
):
    try:
        Path(settings.TMP_DIR).mkdir(parents=True, exist_ok=True)

        tz_path = f"{settings.TMP_DIR}/{tz_file_id}_{tz_file.filename}"
        passport_path = f"{settings.TMP_DIR}/{passport_file_id}_{passport_file.filename}"

        async with aiofiles.open(tz_path, "wb") as out:
            while chunk := await tz_file.read(1024 * 1024):
                await out.write(chunk)

        async with aiofiles.open(passport_path, "wb") as out:
            while chunk := await passport_file.read(1024 * 1024):
                await out.write(chunk)

        tz_task = upload_to_s3.delay(
            tz_path, tz_key, tz_file.content_type, analysis_id, tz_file_id
        )
        passport_task = upload_to_s3.delay(
            passport_path, passport_key, passport_file.content_type, analysis_id, passport_file_id
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "analysis_id": analysis_id,
        "tz": {"name": tz_file.filename, "task_id": tz_task.id, "key": tz_key},
        "passport": {
            "name": passport_file.filename,
            "task_id": passport_task.id,
            "key": passport_key,
        },
    }


@router.get("/files/status/{task_id}")
async def upload_status(task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    return {"task_id": task_id, "status": result.status, "result": result.result}
