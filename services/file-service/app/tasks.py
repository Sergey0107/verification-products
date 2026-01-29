import os

import httpx

from app.celery_app import celery_app
from app.core.config import settings
from app.services.storage import upload_file_path


@celery_app.task(name="file_service.upload_to_s3")
def upload_to_s3(
    file_path: str,
    key: str,
    content_type: str | None,
    analysis_id: str,
    file_id: str,
) -> dict:
    try:
        result = upload_file_path(file_path, key, content_type)
        size_bytes = os.path.getsize(file_path)
        payload = {
            "analysis_id": analysis_id,
            "file_id": file_id,
            "storage_path": result["key"],
            "url": result["url"],
            "mime_type": content_type,
            "size_bytes": size_bytes,
            "status": "uploaded",
        }
    except Exception as exc:
        payload = {
            "analysis_id": analysis_id,
            "file_id": file_id,
            "status": "failed",
            "error": str(exc),
        }
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass

    with httpx.Client(timeout=10) as client:
        client.post(f"{settings.API_GATEWAY_URL}/files/callback", json=payload)

    return payload
