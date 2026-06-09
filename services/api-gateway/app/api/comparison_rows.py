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


async def _get_or_create_user_edit(
    db: AsyncSession, row_id, user_id
) -> UserEdit:
    """Возвращает текущую запись фидбэка пользователя по строке (последнюю) или
    создаёт новую. Одно действие пользователя = одна запись (отметка + коммент),
    а не две раздельные."""
    result = await db.execute(
        select(UserEdit)
        .where(UserEdit.comparison_row_id == row_id)
        .where(UserEdit.user_id == user_id)
        .order_by(UserEdit.edited_at.desc())
    )
    edit = result.scalars().first()
    if edit is None:
        edit = UserEdit(comparison_row_id=row_id, user_id=user_id)
        db.add(edit)
    return edit


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
    # Одно действие пользователя = ОДНА запись фидбэка. Обновляем существующую
    # запись этого пользователя по строке (или создаём), а не плодим новые —
    # иначе отметка и комментарий расходились на две записи.
    comment = payload.comment.strip() if payload.comment and payload.comment.strip() else None
    edit = await _get_or_create_user_edit(db, row_uuid, current_user.id)
    edit.user_result = payload.user_result
    if comment is not None:
        edit.comment = comment
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

    # Прикрепляем комментарий к существующей записи фидбэка пользователя по этой
    # строке (или создаём), чтобы отметка и комментарий жили в ОДНОЙ записи.
    edit = await _get_or_create_user_edit(db, row.id, current_user.id)
    edit.comment = payload.comment
    await db.commit()
    return {"ok": True}
