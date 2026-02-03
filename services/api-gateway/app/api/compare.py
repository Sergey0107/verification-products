from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.db.models.comparison_jobs import ComparisonJob
from app.db.models.analysis import Analysis, ComparisonRow
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
    if status_value == "succeeded":
        await db.execute(
            delete(ComparisonRow).where(ComparisonRow.analysis_id == analysis_id)
        )
        comparisons = payload.get("result", {}).get("comparisons", [])
        for item in comparisons:
            tz_value = item.get("tz_value")
            passport_value = item.get("passport_value")
            tz_value = str(tz_value) if tz_value is not None else None
            passport_value = str(passport_value) if passport_value is not None else None
            row = ComparisonRow(
                analysis_id=analysis_id,
                characteristic=item.get("characteristic") or "",
                tz_value=tz_value,
                passport_value=passport_value,
                tz_quote=item.get("tz_quote"),
                passport_quote=item.get("passport_quote"),
                llm_result=item.get("is_match"),
                user_result=True,
                note=item.get("note"),
            )
            db.add(row)
        await db.execute(
            update(ComparisonJob)
            .where(ComparisonJob.id == job_id)
            .values(status="succeeded", completed_at=datetime.utcnow())
        )
        await db.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(status="ready", updated_at=datetime.utcnow())
        )
    else:
        await db.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(status="failed", updated_at=datetime.utcnow())
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
