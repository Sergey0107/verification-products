from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.deps import parse_uuid
from app.db.models.analysis import (
    Analysis,
    ComparisonRow,
    HiddenCharacteristic,
    ManualCharacteristic,
    UserEdit,
)
from app.db.models.users import User
from app.db.session import get_db
from app.services.manual_evidence import build_manual_evidence

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


class ConfirmedMatchesPayload(BaseModel):
    """Вхождения в паспорте, подтверждённые оператором для этой строки.

    Пустой список — оператор снял подтверждение со всех вариантов; строка
    возвращается к состоянию «выбор не делали».
    """

    match_ids: list[str]


class ManualPassportMatchPayload(BaseModel):
    value: str = Field(min_length=1)
    page: int = Field(ge=1)
    bbox: list[float]
    bbox_units: str = "normalized"

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("bbox must have exactly 4 numbers [left, top, right, bottom]")
        left, top, right, bottom = value
        if not (right > left and bottom > top):
            raise ValueError("bbox must satisfy right > left and bottom > top")
        return value


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


@router.post("/comparison-rows/{row_id}/confirmed-matches")
async def set_confirmed_matches(
    row_id: str,
    payload: ConfirmedMatchesPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Оператор отметил, какие из найденных вхождений относятся к требованию.

    Характеристика может встречаться в паспорте несколько раз (разные рабочие
    точки, повтор в другой таблице), и какие из них правильные — решает
    оператор. Подтверждение выбора означает, что строка признана совпадением,
    поэтому вместе с ним проставляется user_result.
    """
    row_uuid = parse_uuid(row_id)
    await _ensure_row_owned(db, row_uuid, current_user)

    # Порядок вхождений не значим, дубликаты — следствие повторных кликов.
    match_ids = sorted({item for item in payload.match_ids if item})
    has_selection = bool(match_ids)

    await db.execute(
        update(ComparisonRow)
        .where(ComparisonRow.id == row_uuid)
        .values(
            confirmed_passport_matches=match_ids if has_selection else None,
            # Снятие всех отметок возвращает строку к вердикту LLM, а не
            # фиксирует «не совпадает»: оператор просто отменил свой выбор.
            user_result=True if has_selection else None,
        )
    )
    if has_selection:
        db.add(
            UserEdit(
                comparison_row_id=row_uuid,
                user_id=current_user.id,
                user_result=True,
                comment=None,
            )
        )
    await db.commit()
    return {"ok": True, "match_ids": match_ids}


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


@router.post("/comparison-rows/{row_id}/manual-passport-match")
async def create_manual_passport_match(
    row_id: str,
    payload: ManualPassportMatchPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Привязывает ручную аннотацию в паспорте (выделение мышью + значение) как
    match для уже существующей строки сравнения — без повторного запуска
    domain-analyze (сравнение LLM не перезапускается, чтобы не потерять
    накопленные user_result/UserEdit — compare/callback стирает ВСЕ
    comparison_row при каждом прогоне, см. compare.py). Идемпотентно: повторный
    вызов на тот же row_id просто перезаписывает passport_value/passport_evidence."""
    row_uuid = parse_uuid(row_id)
    await _ensure_row_owned(db, row_uuid, current_user)

    value = payload.value.strip()
    evidence = build_manual_evidence(
        document_type="passport",
        value=value,
        page=payload.page,
        bbox=payload.bbox,
        quote_origin="manual_annotation",
    )

    db.add(
        ManualCharacteristic(
            analysis_id=(
                await db.execute(
                    select(ComparisonRow.analysis_id).where(ComparisonRow.id == row_uuid)
                )
            ).scalar_one(),
            document_type="passport",
            linked_characteristic_id=row_id,
            name=value,
            value=value,
            page=payload.page,
            bbox={
                "left": payload.bbox[0],
                "top": payload.bbox[1],
                "right": payload.bbox[2],
                "bottom": payload.bbox[3],
            },
            bbox_units=payload.bbox_units,
            created_by=current_user.id,
        )
    )

    await db.execute(
        update(ComparisonRow)
        .where(ComparisonRow.id == row_uuid)
        .values(passport_value=value, passport_evidence=evidence)
    )
    # Аудит-след — тем же механизмом, что и подтверждение совпадения в модалке,
    # но без отметки Да/Нет (это не суждение, а прикрепление свидетельства).
    db.add(
        UserEdit(
            comparison_row_id=row_uuid,
            user_id=current_user.id,
            user_result=None,
            comment="Ручное сопоставление в паспорте",
        )
    )
    await db.commit()

    return {
        "ok": True,
        "row_id": row_id,
        "passport_value": value,
        "passport_evidence": evidence,
    }


@router.delete("/comparison-rows/{row_id}")
async def delete_comparison_row(
    row_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удаляет характеристику из таблицы сравнения. ComparisonRow целиком
    пересоздаётся при каждом повторном прогоне сравнения (compare_callback),
    поэтому удаление строки саму по себе не сохранилось бы — вместо этого
    запоминаем имя характеристики в hidden_characteristic и фильтруем по нему
    свежие ComparisonRow при каждой выдаче viewer-context. Идемпотентно:
    повторное удаление той же характеристики — no-op."""
    row_uuid = parse_uuid(row_id)
    row_result = await db.execute(
        select(ComparisonRow.analysis_id, ComparisonRow.characteristic)
        .join(Analysis, Analysis.id == ComparisonRow.analysis_id)
        .where(ComparisonRow.id == row_uuid)
        .where(Analysis.user_id == current_user.id)
    )
    row = row_result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Row not found")
    analysis_id, characteristic_name = row

    stmt = insert(HiddenCharacteristic).values(
        analysis_id=analysis_id,
        characteristic_name=characteristic_name,
    )
    stmt = stmt.on_conflict_do_nothing(constraint="uq_hidden_characteristic")
    await db.execute(stmt)
    await db.commit()

    return {"ok": True}
