from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analyses import _ensure_analysis_owner, _upsert_tz_characteristic_review
from app.api.auth import get_current_user
from app.api.deps import parse_uuid
from app.db.models.analysis import ManualCharacteristic
from app.db.models.users import User
from app.db.session import get_db
from app.services.manual_evidence import build_manual_evidence, manual_references_payload

router = APIRouter()

MANUAL_PRODUCT_NAME = "Ручной ввод"


class ManualCharacteristicCreate(BaseModel):
    document_type: str
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    page: int = Field(ge=1)
    bbox: list[float]
    bbox_units: str = "normalized"

    @field_validator("document_type")
    @classmethod
    def _validate_document_type(cls, value: str) -> str:
        if value not in {"tz", "passport"}:
            raise ValueError("document_type must be 'tz' or 'passport'")
        return value

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("bbox must have exactly 4 numbers [left, top, right, bottom]")
        left, top, right, bottom = value
        if not (right > left and bottom > top):
            raise ValueError("bbox must satisfy right > left and bottom > top")
        return value


@router.post("/analyses/{analysis_id}/manual-characteristics")
async def create_manual_characteristic(
    analysis_id: str,
    payload: ManualCharacteristicCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создаёт характеристику, добавленную пользователем вручную путём выделения
    области в документе мышью. Сейчас поддерживается только ТЗ-сторона (кейс А —
    новая характеристика без существующего аналога): она сразу превращается в
    approved-строку TzCharacteristicReview с id "manual-<uuid>", благодаря чему
    автоматически участвует в существующем пайплайне подтверждения/сравнения без
    единой правки в domain-analyze (см. _filtered_tz_payload в tasks.py).

    Для паспорт-стороны (кейс Б — привязка ручной аннотации к уже существующей
    строке сравнения) используется отдельный эндпоинт
    POST /comparison-rows/{row_id}/manual-passport-match, так как там нужен
    конкретный row_id, а не создание независимой характеристики."""
    analysis_uuid = parse_uuid(analysis_id)
    await _ensure_analysis_owner(analysis_uuid, db, current_user)

    if payload.document_type == "passport":
        raise HTTPException(
            status_code=400,
            detail=(
                "Для паспорта используйте "
                "POST /comparison-rows/{row_id}/manual-passport-match — "
                "ручная аннотация в паспорте должна быть привязана к конкретной "
                "характеристике ТЗ."
            ),
        )

    manual_id = uuid4()
    manual_char = ManualCharacteristic(
        id=manual_id,
        analysis_id=analysis_uuid,
        document_type="tz",
        linked_characteristic_id=None,
        product_name=MANUAL_PRODUCT_NAME,
        name=payload.name.strip(),
        value=payload.value.strip(),
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
    db.add(manual_char)

    characteristic_id = f"manual-{manual_id}"
    evidence = build_manual_evidence(
        document_type="tz",
        value=manual_char.value,
        page=manual_char.page,
        bbox=payload.bbox,
        quote_origin="manual_tz_entry",
    )
    references = manual_references_payload(
        value=manual_char.value, page=manual_char.page, bbox=payload.bbox
    )
    await _upsert_tz_characteristic_review(
        analysis_uuid,
        characteristic_id=characteristic_id,
        product_name=MANUAL_PRODUCT_NAME,
        name=manual_char.name,
        value=manual_char.value,
        references=references,
        evidence=evidence,
        approved=True,
        comment=None,
        db=db,
    )
    await db.commit()

    return {
        "characteristic_id": characteristic_id,
        "product_name": MANUAL_PRODUCT_NAME,
        "name": manual_char.name,
        "label": f"{MANUAL_PRODUCT_NAME} — {manual_char.name}",
        "value": manual_char.value,
        "references": references,
        "evidence": evidence,
        "approved": True,
        "comment": None,
    }
