import json
import logging
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def build_s3_url(storage_key: str) -> str:
    endpoint = settings.S3_ENDPOINT.rstrip("/")
    bucket = settings.BUCKET_NAME.strip()
    return f"{endpoint}/{bucket}/{storage_key.lstrip('/')}"


def run_extraction_task(
    analysis_id: str,
    file_id: str,
    file_type: str,
    storage_path: str,
    storage_url: str | None = None,
) -> None:
    file_type = (file_type or "").lower()
    if not storage_path:
        raise ValueError(f"Missing storage_path for file {file_id}")

    if storage_url:
        file_url = storage_url
    else:
        if not settings.BUCKET_NAME:
            raise ValueError("BUCKET_NAME is not set; cannot build S3 URL")
        file_url = build_s3_url(storage_path)

    with httpx.Client(timeout=settings.EXTRACTION_TIMEOUT_SECONDS) as client:
        prompt_resp = client.get(f"{settings.PROMPT_REGISTRY_URL}/prompts/{file_type}")
        prompt_resp.raise_for_status()
        prompt_payload = prompt_resp.json()

        extraction_payload = {
            "analysis_id": analysis_id,
            "file_id": file_id,
            "file_type": file_type,
            "file_url": file_url,
            "prompt": prompt_payload.get("prompt"),
            "schema": prompt_payload.get("schema"),
        }

        extract_resp = client.post(
            f"{settings.EXTRACTION_SERVICE_URL}/extract",
            json=extraction_payload,
        )
        extract_resp.raise_for_status()
        result_payload = extract_resp.json()

    debug_dir = Path(settings.EXTRACTION_DEBUG_DIR)
    debug_dir.mkdir(parents=True, exist_ok=True)
    filename = "test1.json" if file_type == "tz" else "test2.json"
    target = debug_dir / filename
    with target.open("w", encoding="utf-8") as handle:
        json.dump(result_payload, handle, ensure_ascii=True, indent=2)

    return result_payload
