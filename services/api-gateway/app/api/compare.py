from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.db.models.comparison_jobs import ComparisonJob
from app.db.session import get_db
from app.services.comp_data import update_comp_data

router = APIRouter()


@router.post("/compare/callback")
async def compare_callback(payload: dict, db: AsyncSession = Depends(get_db)):
    try:
        job_id = UUID(payload.get("job_id"))
        analysis_id = UUID(payload.get("analysis_id"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ids")

    status_value = payload.get("status")
    if status_value not in {"succeeded", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    values = {
        "status": status_value,
        "updated_at": datetime.utcnow(),
    }
    if status_value == "succeeded":
        values.update(
            {
                "result": payload.get("result"),
                "completed_at": datetime.utcnow(),
            }
        )
    else:
        values.update({"last_error": payload.get("error")})

    await db.execute(
        update(ComparisonJob)
        .where(ComparisonJob.id == job_id)
        .where(ComparisonJob.analysis_id == analysis_id)
        .values(**values)
    )
    await db.commit()

    if status_value == "succeeded":
        update_comp_data(
            "comparison",
            {"analysis_id": str(analysis_id), "status": "succeeded", "result": payload.get("result")},
        )
    else:
        update_comp_data(
            "comparison",
            {
                "analysis_id": str(analysis_id),
                "status": "failed",
                "error": payload.get("error"),
                "raw": payload.get("raw"),
            },
        )

    return {"ok": True}
