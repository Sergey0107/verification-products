from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func, text
from app.db.base import Base


class Analysis(Base):
    __tablename__ = "analysis"
    __table_args__ = {"schema": "analysis"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user.id"), nullable=True)
    status = Column(String, nullable=False)
    extraction_backend = Column(String, nullable=False, server_default=text("'openrouter'"))
    task_id = Column(String, nullable=True)
    product_model = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)


class ComparisonRow(Base):
    __tablename__ = "comparison_row"
    __table_args__ = {"schema": "analysis"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    # Изделие паспорта, к которому относится эта строка сравнения — заполняется,
    # когда паспорт содержит несколько моделей/исполнений одного изделия (см.
    # compare_service._build_comparison_items: product_name уже формировался
    # LLM-сравнением, но раньше терялся при сохранении в эту таблицу). NULL —
    # паспорт с одной моделью, разделение по изделиям не применимо.
    product_name = Column(String, nullable=True)
    characteristic = Column(String, nullable=False)
    tz_value = Column(Text)
    passport_value = Column(Text)
    tz_quote = Column(Text)
    passport_quote = Column(Text)
    tz_evidence = Column(JSONB)
    passport_evidence = Column(JSONB)
    # Все значения характеристики, встреченные в паспорте (документ может
    # упоминать одну характеристику несколько раз с разными, в т.ч.
    # противоречивыми значениями — разные рабочие точки, опечатка в другой
    # таблице и т.п.). passport_value/passport_evidence выше — первое из этого
    # списка (для обратной совместимости с местами кода, ожидающими одно
    # значение). Формат: [{"value": str|null, "evidence": {...}}].
    passport_value_candidates = Column(JSONB, nullable=True)
    llm_result = Column(Boolean)
    user_result = Column(Boolean, nullable=True)
    note = Column(String)
    # Пользовательская корректировка метки ТЗ во вьювере: смещение (offset) и
    # отредактированный текст (custom_text). Перезаписывает позицию/подпись метки,
    # которая изначально пришла из геометрии. Оригинальный tz_evidence не теряется.
    user_tz_mark = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class UserEdit(Base):
    __tablename__ = "user_edit"
    __table_args__ = {"schema": "analysis"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    comparison_row_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_result = Column(Boolean, nullable=True)
    comment = Column(Text)
    edited_at = Column(DateTime, server_default=func.now(), nullable=False)


class TzCharacteristicReview(Base):
    __tablename__ = "tz_characteristic_review"
    __table_args__ = (
        UniqueConstraint("analysis_id", "characteristic_id", name="uq_tz_characteristic_review"),
        {"schema": "analysis"},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    characteristic_id = Column(String, nullable=False)
    product_name = Column(String, nullable=False)
    name = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    references = Column(JSONB, nullable=True)
    evidence = Column(JSONB, nullable=True)
    approved = Column(Boolean, nullable=False, server_default=text("true"))
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)


class ManualCharacteristic(Base):
    """Характеристика, добавленная пользователем вручную путём выделения области
    в документе (ТЗ или паспорт), а не извлечённая LLM. Хранится отдельно от
    TzCharacteristicReview/ComparisonRow — те таблицы имеют другое назначение
    (решение по ревью / денормализованный результат сравнения, стираемый при
    каждом перезапуске сравнения) и не должны знать о происхождении записи."""

    __tablename__ = "manual_characteristic"
    __table_args__ = {"schema": "analysis"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    document_type = Column(String, nullable=False)  # 'tz' | 'passport'
    # NULL для новой характеристики ТЗ (кейс А). Заполнено ID строки
    # TzCharacteristicReview/ComparisonRow, к которой привязана ручная аннотация
    # в паспорте (кейс Б).
    linked_characteristic_id = Column(String, nullable=True)
    product_name = Column(String, nullable=False, server_default=text("'Ручной ввод'"))
    name = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    page = Column(Integer, nullable=False)
    bbox = Column(JSONB, nullable=False)
    bbox_units = Column(String, nullable=False, server_default=text("'normalized'"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.user.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)


class HiddenCharacteristic(Base):
    """Характеристика, которую пользователь удалил из таблицы сравнения.
    ComparisonRow целиком пересоздаётся при каждом повторном прогоне сравнения
    (см. compare_callback в compare.py), поэтому "удаление" не может быть
    флагом на самой строке — вместо этого храним стабильный список скрытых
    имён характеристик отдельно и применяем его как фильтр поверх свежих
    ComparisonRow при каждой выдаче viewer-context (тот же паттерн, что и
    TzCharacteristicReview для комментариев ТЗ-ревью)."""

    __tablename__ = "hidden_characteristic"
    __table_args__ = (
        UniqueConstraint("analysis_id", "characteristic_name", name="uq_hidden_characteristic"),
        {"schema": "analysis"},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    characteristic_name = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


__all__ = [
    "Analysis",
    "ComparisonRow",
    "UserEdit",
    "TzCharacteristicReview",
    "ManualCharacteristic",
    "HiddenCharacteristic",
]
