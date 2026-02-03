from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.analysis import ComparisonRow, UserEdit
from app.db.session import get_db

router = APIRouter()


class UserResultPayload(BaseModel):
    user_result: bool


class CommentPayload(BaseModel):
    comment: str


@router.post("/comparison-rows/{row_id}/user-result")
async def set_user_result(
    row_id: str, payload: UserResultPayload, db: AsyncSession = Depends(get_db)
):
    try:
        row_uuid = UUID(row_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    await db.execute(
        update(ComparisonRow)
        .where(ComparisonRow.id == row_uuid)
        .values(user_result=payload.user_result)
    )
    await db.commit()
    return {"ok": True}


@router.post("/comparison-rows/{row_id}/comment")
async def add_comment(
    row_id: str, payload: CommentPayload, db: AsyncSession = Depends(get_db)
):
    try:
        row_uuid = UUID(row_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    result = await db.execute(
        select(ComparisonRow).where(ComparisonRow.id == row_uuid)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Row not found")

    edit = UserEdit(
        comparison_row_id=row.id,
        comment=payload.comment,
    )
    db.add(edit)
    await db.commit()
    return {"ok": True}
