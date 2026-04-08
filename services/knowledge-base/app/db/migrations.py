from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    AppealClassificationRule,
    Base,
    CanonicalAttribute,
    KnowledgeChunk,
    LetterTemplate,
    NormativeSource,
)
from app.db.session import SessionLocal, engine, is_postgres
from app.core.config import settings
from app.services.ingestion import reindex_source_chunks


DEFAULT_LETTER_TEMPLATES = {
    "recalculation_death": {
        "subject_template": "О рассмотрении обращения о перерасчете в связи со смертью",
        "paragraphs": [
            "Уважаемый(ая) {recipient_name}!",
            "Рассмотрено обращение о перерасчете платы по лицевому счету {account_number} в связи со смертью и изменением состава проживающих.",
            "{response_summary}",
            "Адрес объекта: {recipient_address}.",
            "При наличии дополнительных подтверждающих документов ответ может быть уточнен отдельно.",
        ],
    },
    "recalculation_svo": {
        "subject_template": "О рассмотрении обращения о перерасчете в связи с участием в СВО",
        "paragraphs": [
            "Уважаемый(ая) {recipient_name}!",
            "Рассмотрено обращение о перерасчете платы по услуге {service_name} по лицевому счету {account_number}.",
            "{response_summary}",
            "Период, указанный в документах: {absence_period_from} - {absence_period_to}. Адрес: {recipient_address}.",
            "Настоящее письмо подготовлено на основании представленных документов.",
        ],
    },
    "recalculation_move": {
        "subject_template": "О рассмотрении обращения о перерасчете в связи со сменой места жительства",
        "paragraphs": [
            "Уважаемый(ая) {recipient_name}!",
            "Рассмотрено обращение о перерасчете платы по лицевому счету {account_number} в связи со сменой места жительства.",
            "{response_summary}",
            "Адрес объекта: {recipient_address}.",
        ],
    },
    "recalculation_temporary_absence": {
        "subject_template": "О рассмотрении обращения о перерасчете в связи с временным отсутствием",
        "paragraphs": [
            "Уважаемый(ая) {recipient_name}!",
            "Рассмотрено обращение о перерасчете платы в связи с временным отсутствием по адресу {recipient_address}.",
            "{response_summary}",
            "Период отсутствия: {absence_period_from} - {absence_period_to}.",
        ],
    },
    "recalculation_other": {
        "subject_template": "О рассмотрении обращения о перерасчете",
        "paragraphs": [
            "Уважаемый(ая) {recipient_name}!",
            "Рассмотрено обращение о перерасчете платы по лицевому счету {account_number}.",
            "{response_summary}",
            "Адрес: {recipient_address}.",
        ],
    },
    "authority_prosecutor": {
        "subject_template": "О предоставлении информации по обращению прокуратуры",
        "paragraphs": [
            "В {recipient_name}",
            "В ответ на поступивший запрос сообщаем следующее.",
            "{response_summary}",
            "По материалам обращения установлены данные по адресу: {recipient_address}, лицевой счет {account_number}.",
        ],
    },
    "authority_municipality": {
        "subject_template": "О предоставлении информации по запросу органа местного самоуправления",
        "paragraphs": [
            "В {recipient_name}",
            "Рассмотрен запрос органа местного самоуправления по обращению гражданина.",
            "{response_summary}",
            "По имеющимся данным адрес объекта: {recipient_address}, лицевой счет {account_number}.",
        ],
    },
    "authority_other": {
        "subject_template": "О предоставлении информации по запросу органа",
        "paragraphs": [
            "В {recipient_name}",
            "Рассмотрен поступивший запрос по обращению, находящемуся в обработке.",
            "{response_summary}",
            "По материалам дела адрес объекта: {recipient_address}, лицевой счет {account_number}.",
        ],
    },
    "other": {
        "subject_template": "О рассмотрении обращения",
        "paragraphs": [
            "Уважаемый(ая) {recipient_name}!",
            "Рассмотрено поступившее обращение.",
            "{response_summary}",
            "Адрес: {recipient_address}.",
        ],
    },
}

DEFAULT_PROJECTS = {
    "recalculation": {
        "title": "Перерасчеты и обращения",
        "description": "База знаний для перерасчетов, обращений граждан и ответных писем.",
    },
    "technical_compliance": {
        "title": "Сопоставление ТЗ и паспортов",
        "description": "База знаний для технических характеристик, правил проверки и нормативных материалов.",
    },
}

DEFAULT_APPEAL_CLASSIFICATION_RULES = [
    {
        "project_key": "recalculation",
        "appeal_class": "recalculation_death",
        "rule_name": "Смерть и изменение состава проживающих",
        "match_terms": ["смерт", "умер", "умерш", "свидетельство о смерти"],
        "priority": 10,
    },
    {
        "project_key": "recalculation",
        "appeal_class": "recalculation_svo",
        "rule_name": "Участие в СВО",
        "match_terms": ["сво", "военной операции", "участии в сво", "воинской части"],
        "priority": 20,
    },
    {
        "project_key": "recalculation",
        "appeal_class": "recalculation_move",
        "rule_name": "Смена места жительства",
        "match_terms": ["смена места жительства", "переех", "выбыл", "снятие с регистра"],
        "priority": 30,
    },
    {
        "project_key": "recalculation",
        "appeal_class": "recalculation_temporary_absence",
        "rule_name": "Временное отсутствие",
        "match_terms": ["временн", "отсутств", "не прожива"],
        "priority": 40,
    },
    {
        "project_key": "recalculation",
        "appeal_class": "recalculation_other",
        "rule_name": "Прочий перерасчет",
        "match_terms": ["перерасчет"],
        "priority": 50,
    },
    {
        "project_key": "recalculation",
        "appeal_class": "authority_prosecutor",
        "rule_name": "Запрос прокуратуры",
        "match_terms": ["прокурат"],
        "requester_type": "authority",
        "authority_type": "prosecutor",
        "priority": 5,
    },
    {
        "project_key": "recalculation",
        "appeal_class": "authority_municipality",
        "rule_name": "Запрос муниципалитета",
        "match_terms": ["администрац", "муницип", "мэр", "городск"],
        "requester_type": "authority",
        "authority_type": "municipality",
        "priority": 6,
    },
    {
        "project_key": "recalculation",
        "appeal_class": "authority_other",
        "rule_name": "Прочий орган власти",
        "match_terms": ["орган", "запрос"],
        "requester_type": "authority",
        "authority_type": "other",
        "priority": 7,
    },
]

DEFAULT_CANONICAL_ATTRIBUTES = [
    {
        "domain": "technical_compliance",
        "name": "Производительность",
        "normalized_name": "производительность",
        "unit": "шт/час",
        "value_type": "number",
        "synonyms": ["мощность по производительности", "output"],
    },
    {
        "domain": "technical_compliance",
        "name": "Потребляемая мощность",
        "normalized_name": "потребляемая мощность",
        "unit": "кВт",
        "value_type": "number",
        "synonyms": ["мощность", "power"],
    },
    {
        "domain": "technical_compliance",
        "name": "Напряжение питания",
        "normalized_name": "напряжение питания",
        "unit": "В",
        "value_type": "number",
        "synonyms": ["напряжение", "вольтаж"],
    },
]

DEFAULT_NORMATIVE_SOURCES = [
    {
        "project_key": "recalculation",
        "source_key": "housing_code_rf",
        "title": "Жилищный кодекс Российской Федерации",
        "source_type": "federal_law",
        "jurisdiction": "RU",
        "status": "published",
        "summary": "Базовый федеральный источник по вопросам ЖКХ.",
    },
    {
        "project_key": "recalculation",
        "source_key": "government_354",
        "title": "Постановление Правительства РФ № 354",
        "source_type": "government_resolution",
        "jurisdiction": "RU",
        "status": "published",
        "summary": "Правила предоставления коммунальных услуг.",
    },
]


def _ensure_column(table_name: str, column_name: str, definition: str) -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


def _ensure_postgres_unique_constraint(
    table_name: str,
    old_name: str,
    new_name: str,
    columns_sql: str,
) -> None:
    if not is_postgres():
        return
    with engine.begin() as connection:
        connection.execute(text(f'ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS "{old_name}"'))
        connection.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = '{new_name}'
                    ) THEN
                        ALTER TABLE {table_name}
                        ADD CONSTRAINT "{new_name}" UNIQUE ({columns_sql});
                    END IF;
                END
                $$;
                """
            )
        )


def create_schema() -> None:
    Path(settings.KNOWLEDGE_BASE_STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    if is_postgres():
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    _ensure_column("normative_sources", "project_key", "VARCHAR(64) NOT NULL DEFAULT 'recalculation'")
    _ensure_column("letter_templates", "project_key", "VARCHAR(64) NOT NULL DEFAULT 'recalculation'")
    _ensure_column("appeal_classification_rules", "project_key", "VARCHAR(64) NOT NULL DEFAULT 'recalculation'")
    _ensure_column("knowledge_chunks", "project_key", "VARCHAR(64) NOT NULL DEFAULT 'recalculation'")
    _ensure_column("audit_events", "project_key", "VARCHAR(64) NOT NULL DEFAULT 'shared'")
    _ensure_postgres_unique_constraint(
        "normative_sources",
        "uq_normative_source_key_version",
        "uq_normative_source_project_key_version",
        "project_key, source_key, version",
    )
    _ensure_postgres_unique_constraint(
        "letter_templates",
        "uq_letter_template_version",
        "uq_letter_template_project_key_version",
        "project_key, template_key, version",
    )
    _ensure_postgres_unique_constraint(
        "appeal_classification_rules",
        "uq_appeal_classification_rule_version",
        "uq_classification_rule_project_class_version",
        "project_key, appeal_class, version",
    )


def _seed_letter_templates(db: Session) -> None:
    existing_keys = {
        (item.project_key, item.template_key)
        for item in db.scalars(select(LetterTemplate)).all()
    }
    for template_key, payload in DEFAULT_LETTER_TEMPLATES.items():
        project_key = "recalculation"
        if (project_key, template_key) in existing_keys:
            continue
        db.add(
            LetterTemplate(
                project_key=project_key,
                template_key=template_key,
                subject_template=payload["subject_template"],
                paragraphs=payload["paragraphs"],
                variables=[],
                version=1,
                is_active=True,
                is_published=True,
                is_system=True,
            )
        )


def _seed_classification_rules(db: Session) -> None:
    existing_classes = {
        (item.project_key, item.appeal_class)
        for item in db.scalars(select(AppealClassificationRule)).all()
    }
    for payload in DEFAULT_APPEAL_CLASSIFICATION_RULES:
        if (payload["project_key"], payload["appeal_class"]) in existing_classes:
            continue
        db.add(
            AppealClassificationRule(
                project_key=payload["project_key"],
                appeal_class=payload["appeal_class"],
                rule_name=payload["rule_name"],
                requester_type=payload.get("requester_type"),
                authority_type=payload.get("authority_type"),
                priority=payload["priority"],
                version=1,
                description=payload["rule_name"],
                match_terms=payload["match_terms"],
                is_active=True,
                is_system=True,
            )
        )


def _seed_canonical_attributes(db: Session) -> None:
    existing_names = set(db.scalars(select(CanonicalAttribute.normalized_name)))
    for payload in DEFAULT_CANONICAL_ATTRIBUTES:
        if payload["normalized_name"] in existing_names:
            continue
        db.add(CanonicalAttribute(**payload, is_active=True))


def _seed_normative_sources(db: Session) -> None:
    existing_keys = {
        (item.project_key, item.source_key)
        for item in db.scalars(select(NormativeSource)).all()
    }
    for payload in DEFAULT_NORMATIVE_SOURCES:
        if (payload["project_key"], payload["source_key"]) in existing_keys:
            continue
        db.add(
            NormativeSource(
                **payload,
                version=1,
                is_published=payload.get("status") == "published",
                content_text=payload.get("summary"),
                metadata_json={},
            )
        )


def bootstrap_data() -> None:
    with SessionLocal() as db:
        _seed_letter_templates(db)
        _seed_classification_rules(db)
        _seed_canonical_attributes(db)
        _seed_normative_sources(db)
        db.flush()
        db.execute(
            text(
                "UPDATE letter_templates SET project_key = 'recalculation' "
                "WHERE COALESCE(project_key, '') = ''"
            )
        )
        db.execute(
            text(
                "UPDATE appeal_classification_rules SET project_key = 'recalculation' "
                "WHERE COALESCE(project_key, '') = ''"
            )
        )
        db.execute(
            text(
                "UPDATE normative_sources SET project_key = 'recalculation' "
                "WHERE COALESCE(project_key, '') = ''"
            )
        )
        db.execute(
            text(
                "UPDATE knowledge_chunks SET project_key = 'recalculation' "
                "WHERE COALESCE(project_key, '') = ''"
            )
        )
        db.execute(
            text(
                "UPDATE audit_events SET project_key = 'shared' "
                "WHERE COALESCE(project_key, '') = ''"
            )
        )
        for source in db.scalars(select(NormativeSource)).all():
            has_chunks = db.scalar(
                select(KnowledgeChunk.id).where(KnowledgeChunk.source_id == source.id).limit(1)
            )
            if has_chunks:
                continue
            if source.content_text:
                reindex_source_chunks(db, source, actor="bootstrap")
        db.commit()
