from contextlib import contextmanager
from datetime import datetime, timedelta
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
from app.db.models.extraction_jobs import ExtractionJob
from app.db.models.extraction_results import ExtractionResult
from app.db.session_sync import SessionLocal
from app.services.comp_data import update_comp_data
from app.services.extraction_jobs import (
    clear_missing_marker,
    find_job_by_external_id,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    mark_missing_on_poll,
    was_missing_on_last_poll,
)
from app.services.extraction_tasks import postprocess_extraction_result, run_extraction_task
from app.services.paddleocr_vl_convert import convert_paddleocr_vl_callback_result

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


@celery_app.task(
    bind=True,
    name="api_gateway.finalize_extraction",
    queue="api_gateway",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def finalize_extraction_task(
    self,
    job_id: str,
    analysis_id: str,
    file_id: str,
    file_type: str,
    extraction_backend: str | None,
    status: str,
    result_payload: dict | None,
    error: str | None,
) -> None:
    """Завершающая половина extract_file для async-режима (backend
    yandex_vision_ocr) — запускается из POST /internal/extraction-callback,
    когда paddleocr-vl-service сообщает, что job (запущенный extract_file
    ранее, см. её ветку result_payload.get("async")) закончился — успешно
    или окончательным провалом (после исчерпания собственных постраничных
    ретраев на стороне paddleocr-vl-service, см. job_queue.py там).

    Тот же advisory lock, что у extract_file, и по тому же job_id
    (extraction_job.id, не external_job_id) — на случай, если callback
    почему-то пришёл дважды (сеть повторно доставила POST) или пересёкся с
    остаточным fallback-поллингом: работать с одним и тем же extraction_job
    параллельно из двух copies так же небезопасно, как и раньше."""
    attempt = self.request.retries + 1
    log_extra = {
        "analysis_id": analysis_id, "file_id": file_id, "file_type": file_type,
        "step": "finalize_extraction",
    }
    started_at = time.monotonic()

    with _extraction_job_lock(job_id) as acquired:
        if not acquired:
            logger.warning(
                "finalize_extraction: another copy of job_id=%s is already running, skipping",
                job_id, extra=log_extra,
            )
            return

        if status != "succeeded":
            error_detail = error or "paddleocr-vl-service reported job failure without details"
            logger.error(
                "finalize_extraction: async job failed job_id=%s error=%s",
                job_id, error_detail, extra=log_extra,
            )
            mark_job_failed(job_id, error_detail, "failed")
            with SessionLocal() as session:
                session.execute(
                    text("UPDATE analysis.analysis SET status=:status, updated_at=:updated_at WHERE id=:id"),
                    {"status": "failed", "updated_at": datetime.utcnow(), "id": analysis_id},
                )
                session.commit()
            update_comp_data(
                "extraction",
                {
                    "analysis_id": analysis_id,
                    "status": "failed",
                    "error": error_detail,
                    "file_type": file_type,
                },
            )
            return

        try:
            # Callback от paddleocr-vl-service несёт СЫРОЙ результат пайплайна
            # ({"paddle": ..., "yandex": ...}) — конвертацию в result.products
            # (группировка по variant, bbox, extraction_metadata) в синхронном
            # пути делает extraction-service (_paddleocr_vl_specs_to_products
            # внутри _extract_via_paddleocr_vl) до возврата ответа сюда; в
            # async-пути extraction-service этот финальный результат никогда
            # не видит (только маркер {"async": True} при старте), поэтому
            # та же конвертация обязана произойти здесь, иначе payload
            # сохранится в неправильном формате и продукты/bbox будут
            # недоступны фронтенду.
            converted = convert_paddleocr_vl_callback_result(
                result_payload or {},
                analysis_id=analysis_id,
                file_id=file_id,
                file_type=file_type,
            )
            # Та же нормализация/валидация, что синхронный путь получает
            # внутри run_extraction_task — обязательна для сохранения
            # точности данных одинаково для обоих путей (см. docstring
            # postprocess_extraction_result).
            normalized = postprocess_extraction_result(
                converted,
                analysis_id=analysis_id,
                file_id=file_id,
                file_type=file_type,
                log_extra=log_extra,
            )
            _finalize_extraction(
                analysis_id=analysis_id,
                file_type=file_type,
                extraction_backend=extraction_backend,
                result_payload=normalized,
                log_extra=log_extra,
            )
        except Exception as exc:
            fail_status = "failed" if self.request.retries >= self.max_retries else "retrying"
            error_detail = "".join([str(exc), "\n\nGateway worker traceback:\n", traceback.format_exc()])
            logger.exception(
                "finalize_extraction failed job_id=%s attempt=%s status=%s elapsed=%.2fs",
                job_id, attempt, fail_status, time.monotonic() - started_at, extra=log_extra,
            )
            mark_job_failed(job_id, error_detail, fail_status)
            if fail_status == "failed":
                with SessionLocal() as session:
                    session.execute(
                        text("UPDATE analysis.analysis SET status=:status, updated_at=:updated_at WHERE id=:id"),
                        {"status": "failed", "updated_at": datetime.utcnow(), "id": analysis_id},
                    )
                    session.commit()
            update_comp_data(
                "extraction",
                {"analysis_id": analysis_id, "status": fail_status, "error": error_detail, "file_type": file_type},
            )
            raise
        else:
            mark_job_succeeded(job_id)
            logger.info(
                "finalize_extraction finished in %.2fs job_id=%s",
                time.monotonic() - started_at, job_id, extra=log_extra,
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
            job_id=job_id,
        )

        if result_payload.get("async") is True:
            # Извлечение продолжается в фоне на стороне paddleocr-vl-service
            # (см. job_queue.py там) — эта Celery-задача СВОЮ часть работы
            # выполнила (запустила job) и завершается успешно ПРЯМО СЕЙЧАС,
            # не дожидаясь результата: worker-слот освобождается для других
            # задач вместо того, чтобы висеть в одном HTTP-запросе десятки
            # минут. extraction_job остаётся в статусе "running" (не
            # succeeded — работа объективно не закончена) с сохранённым
            # external_job_id; финал придёт через
            # POST /internal/extraction-callback (см. finalize_extraction
            # ниже), который вызывает _finalize_extraction — тот же код,
            # что шёл бы дальше в этой функции при синхронном пути.
            external_job_id = result_payload.get("job_id")
            mark_job_running(job_id, attempt, external_job_id=external_job_id)
            logger.info(
                "extract_file: async extraction started, external_job_id=%s — "
                "awaiting callback, Celery task ends here",
                external_job_id,
                extra=log_extra,
            )
            return

        _finalize_extraction(
            analysis_id=analysis_id,
            file_type=file_type,
            extraction_backend=extraction_backend,
            result_payload=result_payload,
            log_extra=log_extra,
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


def _finalize_extraction(
    *,
    analysis_id: str,
    file_type: str,
    extraction_backend: str | None,
    result_payload: dict,
    log_extra: dict,
) -> None:
    """Сохраняет результат извлечения и продвигает конвейер анализа дальше
    (tz_review / запуск сравнения). Вынесено из _run_extract_file, чтобы
    один и тот же код обслуживал оба пути получения result_payload:
    синхронный (backend вернул результат сразу, эта функция вызывается
    прямо из _run_extract_file) и асинхронный (backend вернул job_id, эта
    функция вызывается позже из finalize_extraction_task — Celery-задачи,
    которую запускает POST /internal/extraction-callback при получении
    результата от paddleocr-vl-service)."""
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


@celery_app.task(name="api_gateway.poll_stuck_extraction_jobs")
def poll_stuck_extraction_jobs() -> None:
    """Fallback для async-режима (backend yandex_vision_ocr): callback от
    paddleocr-vl-service уже ретраится там до 6 раз с backoff (см.
    job_queue.py._deliver_callback), но если ВСЕ попытки пришлись на окно,
    когда api-gateway был недоступен (рестарт/деплой), extraction_job
    остался бы в статусе "running" навсегда — эта периодическая задача
    (запускается Celery Beat, см. celery_app.py beat_schedule) раз в 3
    минуты проверяет такие "зависшие" job'ы напрямую через
    GET {paddleocr-vl-service}/jobs/{external_job_id} и сама вызывает
    finalize_extraction_task, если находит готовый результат.

    Не вмешивается в job'ы, которые просто ещё выполняются в срок — порог
    STUCK_EXTRACTION_JOB_THRESHOLD_SECONDS даёт достаточный запас над
    обычным временем обработки и над окном ретраев самого callback."""
    threshold = datetime.utcnow() - timedelta(seconds=settings.STUCK_EXTRACTION_JOB_THRESHOLD_SECONDS)
    with SessionLocal() as session:
        stuck_jobs = session.execute(
            select(ExtractionJob)
            .where(ExtractionJob.status == "running")
            .where(ExtractionJob.external_job_id.is_not(None))
            .where(ExtractionJob.updated_at < threshold)
        ).scalars().all()
        # Копируем нужные поля до закрытия сессии — избегаем
        # DetachedInstanceError при обращении к атрибутам ниже.
        stuck = [
            {
                "id": str(row.id),
                "analysis_id": str(row.analysis_id),
                "file_id": str(row.file_id),
                "file_type": row.file_type,
                "external_job_id": row.external_job_id,
            }
            for row in stuck_jobs
        ]

    if not stuck:
        return

    logger.warning("poll_stuck_extraction_jobs: found %d stuck job(s), checking paddleocr-vl-service directly", len(stuck))

    for job in stuck:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{settings.PADDLEOCR_VL_SERVICE_URL.rstrip('/')}/jobs/{job['external_job_id']}"
                )
            if resp.status_code == 404:
                # Не проваливаем сразу на первый 404 — job на paddleocr-vl-
                # service мог быть ещё жив, а 404 вызван кратковременной
                # нестыковкой (реальный инцидент: heartbeat meta-ключа не
                # обновлялся достаточно часто, GET успевал 404-ить на живой
                # job). Требуем ДВА подряд 404 в разных тиках (~3 минуты
                # между ними) прежде чем считать job окончательно потерянным
                # — если job действительно жив, следующий heartbeat (см.
                # job_queue.py _periodic_flush) успеет обновить updated_at
                # раньше следующей проверки, и запись перестанет попадать в
                # выборку "stuck" вовсе.
                if was_missing_on_last_poll(job["id"]):
                    logger.error(
                        "poll_stuck_extraction_jobs: external_job_id=%s still not found on "
                        "paddleocr-vl-service after a second check, marking extraction_job=%s as failed",
                        job["external_job_id"], job["id"],
                    )
                    finalize_extraction_task.delay(
                        job_id=job["id"],
                        analysis_id=job["analysis_id"],
                        file_id=job["file_id"],
                        file_type=job["file_type"],
                        extraction_backend="yandex_vision_ocr",
                        status="failed",
                        result_payload=None,
                        error="paddleocr-vl-service job not found (TTL expired, callback never delivered)",
                    )
                else:
                    logger.warning(
                        "poll_stuck_extraction_jobs: external_job_id=%s not found on paddleocr-vl-service "
                        "(1st check) — will re-check next tick before giving up",
                        job["external_job_id"],
                    )
                    mark_missing_on_poll(job["id"])
                continue

            clear_missing_marker(job["id"])

            resp.raise_for_status()
            data = resp.json()
            remote_status = data.get("status")
            if remote_status not in ("succeeded", "failed"):
                # Всё ещё running/queued там — реально не зависло, просто
                # медленно; ничего не делаем, следующий тик проверит снова.
                continue

            logger.info(
                "poll_stuck_extraction_jobs: external_job_id=%s resolved via fallback poll, status=%s",
                job["external_job_id"], remote_status,
            )
            finalize_extraction_task.delay(
                job_id=job["id"],
                analysis_id=job["analysis_id"],
                file_id=job["file_id"],
                file_type=job["file_type"],
                extraction_backend="yandex_vision_ocr",
                status=remote_status,
                result_payload=data.get("result"),
                error=data.get("error"),
            )
        except Exception:
            logger.exception(
                "poll_stuck_extraction_jobs: failed to check external_job_id=%s, will retry next tick",
                job["external_job_id"],
            )
