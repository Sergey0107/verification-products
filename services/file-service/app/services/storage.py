from pathlib import Path

import boto3

from app.core.config import settings


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.AWS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_KEY,
    )


def upload_file_path(file_path: str, key: str, content_type: str | None = None) -> dict:
    if not settings.BUCKET_NAME:
        raise ValueError("BUCKET_NAME is not set")
    path = Path(file_path)
    if not path.exists():
        raise ValueError("File not found")

    client = _client()
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    client.upload_file(str(path), settings.BUCKET_NAME, key, ExtraArgs=extra_args or None)
    url = f"{settings.S3_ENDPOINT.rstrip('/')}/{settings.BUCKET_NAME}/{key}"
    return {"bucket": settings.BUCKET_NAME, "key": key, "url": url}


def download_file_path(key: str, target_path: str) -> str:
    if not settings.BUCKET_NAME:
        raise ValueError("BUCKET_NAME is not set")
    client = _client()
    client.download_file(settings.BUCKET_NAME, key, target_path)
    return target_path
