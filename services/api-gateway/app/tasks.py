from contextlib import contextmanager
from datetime import datetime
import logging
import time
import traceback
import zlib

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.celery_app import celery_app
from app.core.config import settings
from app.db.models.comparison_jobs import ComparisonJob
from app.db.models.analysis import TzCharacteristicReview
from app.db.models.extraction_results import ExtractionResult
from app.db.session_sync import SessionLocal
from app.services.comp_data import update_comp_data
from app.services.extraction_jobs import (
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from app.services.extraction_tasks import run_extraction_task

logger = logging.getLogger(__name__)


def _advisory_lock_key(job_id: str) -> int:
    # pg_try_advisory_lock хочет bigint; job_id — uuid-строка, поэтому сжимаем
    # её в 32-битное число через crc32. Коллизия между разными job_id технически
    # возможна, но это лишь означает избыточную сериализацию двух НЕСВЯЗАННЫХ
    # задач — не потерю данных, так что цена коллизии минимальна.
    return zlib.crc32(job_id.encode()) & 0x7FFFFFFF


@contextmanager
def _extraction_job_lock(job_id: str):
    """Не даёт двум копиям одной extract_file реально выполнять работу одновременно.

    task_acks_late=True гарантирует, что сообщение не потеряется при падении
    воркера, но ценой этого — RabbitMQ доставляет задачу повторно при обрыве
    AMQP-канала (например, если ack не пришёл за 30 минут), и тогда две копии
    одной и той же задачи выполняются параллельно, удваивая нагрузку на и без
    того перегруженный внешний сервис извлечения. mark_job_running делает
    статус в БД идемпотентным, но не мешает самой РАБОТЕ дублироваться.

    Сессионный advisory lock: держится, пока живо это соединение, и
    автоматически освобождается, если процесс аварийно упадёт — в отличие от
    флага в таблице, который пришлось бы вручную снимать после краша.
    """
    key = _advisory_lock_key(job_id)
    session = SessionLocal()
    try:
        acquired = session.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        ).scalar()
        if not acquired:
            session.close()
            yield False
            return
        try:
            yield True
        finally:
            session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            session.commit()
    finally:
        session.close()


def _approved_review_characteristics(session, analysis_id: str) -> list[TzCharacteristicReview]:
    return (
        session.execute(
            select(TzCharacteristicReview)
            .where(TzCharacteristicReview.analysis_id == analysis_id)
            .where(TzCharacteristicReview.approved.is_(True))
            .order_by(TzCharacteristicReview.created_at.asc())
        )
        .scalars()
        .all()
    )


def _target_characteristics(rows: list[TzCharacteristicReview]) -> list[dict]:
    return [
        {
            "characteristic_id": row.characteristic_id,
            "product_name": row.product_name,
            "name": row.name,
            "value": row.value,
        }
        for row in rows
    ]


def _filtered_tz_payload(rows: list[TzCharacteristicReview]) -> dict:
    products: dict[str, dict] = {}
    for row in rows:
        product = products.setdefault(
            row.product_name,
            {
                "product_name": row.product_name,
                "characteristics": [],
            },
        )
        product["characteristics"].append(
            {
                "name": row.name,
                "value": row.value,
                "references": row.references or [],
                "evidence": row.evidence,
            }
        )
    return {"products": list(products.values())}


@celery_app.task(
    bind=True,
    name="api_gateway.extract_file",
    queue="api_gateway",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def extract_file(
    self,
    job_id: str,
    analysis_id: str,
    file_id: str,
    file_type: str,
    storage_path: str,
    storage_url: str | None = None,
    extraction_backend: str | None = None,
    target_characteristics: list[dict] | None = None,
    product_model: str | None = None,
) -> None:
    attempt = self.request.retries + 1
    log_extra = {
        "analysis_id": analysis_id, "file_id": file_id, "file_type": file_type, "step": "extract_file",
    }
    started_at = time.monotonic()

    with _extraction_job_lock(job_id) as acquired:
        if not acquired:
            # Другая копия этой же задачи (redelivered после обрыва AMQP-канала
            # или дублирующего сообщения) уже выполняется прямо сейчас — не
            # запускаем работу второй раз и не трогаем статус job, которым
            # владеет активная копия. Задача просто тихо завершается: реальная
            # работа продолжается в той копии, что держит блокировку.
            logger.warning(
                "extract_file: another copy of job_id=%s is already running, skipping duplicate delivery",
                job_id,
                extra=log_extra,
            )
            return
        _run_extract_file(
            self,
            attempt=attempt,
            started_at=started_at,
            log_extra=log_extra,
            job_id=job_id,
            analysis_id=analysis_id,
            file_id=file_id,
            file_type=file_type,
            storage_path=storage_path,
            storage_url=storage_url,
            extraction_backend=extraction_backend,
            target_characteristics=target_characteristics,
            product_model=product_model,
        )


def _run_extract_file(
    self,
    *,
    attempt: int,
    started_at: float,
    log_extra: dict,
    job_id: str,
    analysis_id: str,
    file_id: str,
    file_type: str,
    storage_path: str,
    storage_url: str | None,
    extraction_backend: str | None,
    target_characteristics: list[dict] | None,
    product_model: str | None,
) -> None:
    logger.info(
        "extract_file task started job_id=%s attempt=%s backend=%s",
        job_id, attempt, extraction_backend,
        extra=log_extra,
    )
    mark_job_running(job_id, attempt)
    try:
        result_payload = run_extraction_task(
            analysis_id=analysis_id,
            file_id=file_id,
            file_type=file_type,
            storage_path=storage_path,
            storage_url=storage_url,
            extraction_backend=extraction_backend,
            target_characteristics=target_characteristics,
            product_model=product_model,
        )
        with SessionLocal() as session:
            stmt = (
                insert(ExtractionResult)
                .values(
                    analysis_id=analysis_id,
                    file_type=file_type,
                    payload=result_payload,
                    updated_at=datetime.utcnow(),
                )
                .on_conflict_do_update(
                    index_elements=["analysis_id", "file_type"],
                    set_={
                        "payload": result_payload,
                        "updated_at": datetime.utcnow(),
                    },
                )
            )
            session.execute(stmt)
            session.commit()

            results = session.execute(
                select(ExtractionResult).where(ExtractionResult.analysis_id == analysis_id)
            ).scalars().all()
            by_type = {row.file_type: row.payload for row in results}
            update_comp_data(
                "extraction",
                {
                    "analysis_id": analysis_id,
                    "status": "succeeded",
                    "data": by_type,
                },
            )

            if file_type == "tz":
                session.execute(
                    text("UPDATE analysis.analysis SET status=:status, updated_at=:updated_at WHERE id=:id"),
                    {
                        "status": "tz_review",
                        "updated_at": datetime.utcnow(),
                        "id": analysis_id,
                    },
                )
                session.commit()
                logger.info(
                    "extract_file: analysis moved to tz_review", extra=log_extra,
                )

            if file_type == "passport" and "passport" in by_type:
                approved_rows = _approved_review_characteristics(session, analysis_id)
                if not approved_rows:
                    raise ValueError("Cannot compare without approved TZ characteristics")

                create_job = (
                    insert(ComparisonJob)
                    .values(
                        analysis_id=analysis_id,
                        status="queued",
                        updated_at=datetime.utcnow(),
                    )
                    .on_conflict_do_nothing(index_elements=["analysis_id"])
                    .returning(ComparisonJob.id)
                )
                job_result = session.execute(create_job)
                compare_job_id = job_result.scalar_one_or_none()
                session.commit()

                if compare_job_id:
                    session.execute(
                        text("UPDATE analysis.analysis SET status=:status, updated_at=:updated_at WHERE id=:id"),
                        {
                            "status": "analyzing_data",
                            "updated_at": datetime.utcnow(),
                            "id": analysis_id,
                        },
                    )
                    session.commit()
                    payload = {
                        "job_id": str(compare_job_id),
                        "analysis_id": analysis_id,
                        "tz_data": _filtered_tz_payload(approved_rows),
                        "passport_data": by_type["passport"],
                        # Сравнение выполняет LLM того же провайдера, которым
                        # извлекались характеристики: выбор в модалке задаёт оба
                        # этапа анализа сразу.
                        "extraction_backend": extraction_backend,
                    }
                    logger.info(
                        "extract_file: analysis moved to analyzing_data, comparison job_id=%s "
                        "tz_characteristics=%d",
                        compare_job_id, len(approved_rows),
                        extra=log_extra,
                    )
                    with httpx.Client(timeout=settings.EXTRACTION_TIMEOUT_SECONDS) as client:
                        client.post(
                            f"{settings.DOMAIN_ANALYZE_URL}/compare/jobs",
                            json=payload,
                        )
    except Exception as exc:
        status = "failed" if self.request.retries >= self.max_retries else "retrying"
        error_detail = "".join(
            [
                str(exc),
                "\n\nGateway worker traceback:\n",
                traceback.format_exc(),
            ]
        )
        logger.exception(
            "Extraction task failed: analysis_id=%s file_id=%s file_type=%s job_id=%s attempt=%s "
            "status=%s elapsed=%.2fs",
            analysis_id,
            file_id,
            file_type,
            job_id,
            attempt,
            status,
            time.monotonic() - started_at,
            extra=log_extra,
        )
        mark_job_failed(job_id, error_detail, status)
        if status == "failed":
            with SessionLocal() as session:
                session.execute(
                    text("UPDATE analysis.analysis SET status=:status, updated_at=:updated_at WHERE id=:id"),
                    {
                        "status": "failed",
                        "updated_at": datetime.utcnow(),
                        "id": analysis_id,
                    },
                )
                session.commit()
        update_comp_data(
            "extraction",
            {
                "analysis_id": analysis_id,
                "status": status,
                "error": error_detail,
                "file_type": file_type,
            },
        )
        raise
    else:
        mark_job_succeeded(job_id)
        logger.info(
            "extract_file task finished in %.2fs job_id=%s",
            time.monotonic() - started_at, job_id,
            extra=log_extra,
        )
