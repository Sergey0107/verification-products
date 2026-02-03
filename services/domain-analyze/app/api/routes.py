from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.tasks import compare_documents

router = APIRouter()


class CompareRequest(BaseModel):
    job_id: str
    analysis_id: str
    tz_data: dict
    passport_data: dict


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/compare/jobs")
async def create_compare_job(payload: CompareRequest):
    if not payload.job_id or not payload.analysis_id:
        raise HTTPException(status_code=400, detail="Invalid ids")
    compare_documents.apply_async(
        args=[
            payload.job_id,
            payload.analysis_id,
            payload.tz_data,
            payload.passport_data,
        ],
        task_id=payload.job_id,
    )
    return {"ok": True, "job_id": payload.job_id}
