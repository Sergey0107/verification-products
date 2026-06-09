from datetime import datetime, timedelta

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

# Фронт сохраняет одно действие двумя запросами подряд: сначала /user-result,
# затем /comment. Чтобы они попали в ОДНУ запись (а не задвоились), комментарий
# прикрепляется к только что созданной записи отметки в пределах этого окна.
SAME_ACTION_WINDOW = timedelta(seconds=15)


class UserResultPayload(BaseModel):
    user_result: bool
    comment: str | None = None


class CommentPayload(BaseModel):
    comment: str


async def _ensure_row_owned(db: AsyncSession, row_uuid, user: User) -> None:
    result = await db.execute(
        select(ComparisonRow.id)
        .join(Analysis, Analysis.id == ComparisonRow.analysis_id)
        .where(ComparisonRow.id == row_uuid)
        .where(Analysis.user_id == user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Row not found")


@router.post("/comparison-rows/{row_id}/user-result")
async def set_user_result(
    row_id: str,
    payload: UserResultPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row_uuid = parse_uuid(row_id)
    await _ensure_row_owned(db, row_uuid, current_user)

    await db.execute(
        update(ComparisonRow).where(ComparisonRow.id == row_uuid).values(user_result=payload.user_result)
    )
    # Каждая отметка — НОВАЯ запись фидбэка (история накапливается, не перезаписываем).
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
    await _ensure_row_owned(db, row_uuid, current_user)

    # Если этот /comment — часть того же действия, что и только что прошедший
    # /user-result (свежая запись этого пользователя БЕЗ комментария), дописываем
    # комментарий в неё → одно действие = одна запись. Иначе — новая запись
    # (отдельный комментарий накапливается в истории).
    recent = await db.execute(
        select(UserEdit)
        .where(UserEdit.comparison_row_id == row_uuid)
        .where(UserEdit.user_id == current_user.id)
        .where(UserEdit.comment.is_(None))
        .where(UserEdit.edited_at >= datetime.utcnow() - SAME_ACTION_WINDOW)
        .order_by(UserEdit.edited_at.desc())
    )
    edit = recent.scalars().first()
    if edit is not None:
        edit.comment = payload.comment
    else:
        db.add(
            UserEdit(
                comparison_row_id=row_uuid,
                user_id=current_user.id,
                comment=payload.comment,
            )
        )
    await db.commit()
    return {"ok": True}
