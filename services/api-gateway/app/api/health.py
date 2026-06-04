import httpx
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/file-service/health")
async def ping_file_service():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{settings.FILE_SERVICE_URL}/health")
        return response.json()
