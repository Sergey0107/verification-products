from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.deps import parse_uuid
from app.db.models.analysis import Analysis, ComparisonRow, UserEdit
from app.db.models.users import User
from app.db.session import get_db

router = APIRouter()


class UserResultPayload(BaseModel):
    user_result: bool
    comment: str | None = None


class CommentPayload(BaseModel):
    comment: str


@router.post("/comparison-rows/{row_id}/user-result")
async def set_user_result(
    row_id: str,
    payload: UserResultPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row_uuid = parse_uuid(row_id)

    result = await db.execute(
        select(ComparisonRow.id)
        .join(Analysis, Analysis.id == ComparisonRow.analysis_id)
        .where(ComparisonRow.id == row_uuid)
        .where(Analysis.user_id == current_user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Row not found")

    await db.execute(
        update(ComparisonRow).where(ComparisonRow.id == row_uuid).values(user_result=payload.user_result)
    )
    # Фиксируем отметку (Да/Нет) вместе с автором как отдельную запись фидбэка,
    # чтобы во viewer-context показать, кто и что выбрал.
    comment = payload.comment.strip() if payload.comment and payload.comment.strip() else None
    db.add(
        UserEdit(
            comparison_row_id=row_uuid,
            user_id=current_user.id,
            user_result=payload.user_result,
            comment=comment,
        )
    )
    await db.commit()
    return {"ok": True}


@router.post("/comparison-rows/{row_id}/comment")
async def add_comment(
    row_id: str,
    payload: CommentPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row_uuid = parse_uuid(row_id)

    result = await db.execute(
        select(ComparisonRow)
        .join(Analysis, Analysis.id == ComparisonRow.analysis_id)
        .where(ComparisonRow.id == row_uuid)
        .where(Analysis.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Row not found")

    edit = UserEdit(
        comparison_row_id=row.id,
        user_id=current_user.id,
        comment=payload.comment,
    )
    db.add(edit)
    await db.commit()
    return {"ok": True}
