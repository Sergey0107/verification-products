import shutil
import subprocess
import tempfile
import shutil
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from celery.result import AsyncResult

from app.celery_app import celery_app
from app.core.config import settings
from app.services.storage import download_file_path
from app.tasks import upload_to_s3

router = APIRouter()


def _is_docx_document(name: str, content_type: str | None) -> bool:
    suffix = Path(name).suffix.lower()
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return (
        suffix in {".doc", ".docx"}
        or normalized
        in {
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
    )


def _is_pdf_document(name: str, content_type: str | None) -> bool:
    suffix = Path(name).suffix.lower()
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return suffix == ".pdf" or normalized == "application/pdf"


def _safe_download_name(name: str) -> str:
    return Path(name or "document").name or "document"


def _convert_office_document_to_pdf(source_path: Path, output_dir: Path) -> Path:
    profile_dir = output_dir / "lo-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "soffice",
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--nodefault",
        f"-env:UserInstallation=file://{profile_dir.as_posix()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "LibreOffice conversion failed").strip()
        raise RuntimeError(detail)

    pdf_path = output_dir / f"{source_path.stem}.pdf"
    if pdf_path.exists():
        return pdf_path

    candidates = sorted(output_dir.glob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise RuntimeError("LibreOffice did not create a PDF preview")
    return candidates[0]


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


@router.get("/files/download")
async def download_file(
    key: str,
    name: str,
    background_tasks: BackgroundTasks,
):
    try:
        downloads_dir = Path(settings.TMP_DIR) / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        target_path = downloads_dir / f"{uuid4()}_{name}"
        download_file_path(key, str(target_path))
        background_tasks.add_task(target_path.unlink, missing_ok=True)
        return FileResponse(
            path=str(target_path),
            filename=name,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/files/preview")
async def preview_file(
    key: str,
    name: str,
    background_tasks: BackgroundTasks,
    content_type: str | None = None,
):
    safe_name = _safe_download_name(name)
    if not (_is_pdf_document(safe_name, content_type) or _is_docx_document(safe_name, content_type)):
        raise HTTPException(status_code=415, detail="Preview supports PDF and Word documents only")

    try:
        Path(settings.TMP_DIR).mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="preview-", dir=settings.TMP_DIR))
        source_path = work_dir / safe_name
        download_file_path(key, str(source_path))
        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)

        if _is_pdf_document(safe_name, content_type):
            return FileResponse(
                path=str(source_path),
                filename=safe_name,
                media_type="application/pdf",
                content_disposition_type="inline",
            )

        pdf_path = _convert_office_document_to_pdf(source_path, work_dir)
        preview_name = f"{Path(safe_name).stem}.pdf"
        return FileResponse(
            path=str(pdf_path),
            filename=preview_name,
            media_type="application/pdf",
            content_disposition_type="inline",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Document preview conversion timed out")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
