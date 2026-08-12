from datetime import datetime

from sqlalchemy import select, update

from app.db.models.extraction_jobs import ExtractionJob
from app.db.session_sync import SessionLocal


def mark_job_running(job_id: str, attempt: int, external_job_id: str | None = None) -> None:
    values = {
        "status": "running",
        "attempts": attempt,
        "updated_at": datetime.utcnow(),
    }
    if external_job_id is not None:
        # Только для async-режима (backend yandex_vision_ocr) — id job'а на
        # стороне paddleocr-vl-service, нужен для сопоставления входящего
        # callback и для fallback-поллинга (см. finalize_stuck_extractions).
        values["external_job_id"] = external_job_id
    with SessionLocal() as session:
        session.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id == job_id)
            .values(**values)
        )
        session.commit()


def find_job_by_external_id(external_job_id: str) -> dict | None:
    """Возвращает плоский dict (не ORM-объект — избегаем DetachedInstanceError
    после закрытия сессии), нужные поля для сопоставления и финализации
    callback'а: id, analysis_id, file_id, file_type, backend, attempts."""
    with SessionLocal() as session:
        row = session.execute(
            select(ExtractionJob).where(ExtractionJob.external_job_id == external_job_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": str(row.id),
            "analysis_id": str(row.analysis_id),
            "file_id": str(row.file_id),
            "file_type": row.file_type,
            "attempts": row.attempts,
        }


def mark_job_failed(job_id: str, error: str, status: str) -> None:
    with SessionLocal() as session:
        session.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id == job_id)
            .values(
                status=status,
                last_error=error,
                updated_at=datetime.utcnow(),
            )
        )
        session.commit()


# Маркер во временном поле last_error (пока job ещё "running") — отличаем
# "видели 404 на прошлом тике poll_stuck_extraction_jobs, ждём подтверждения"
# от реальной ошибки выполнения. Используем существующее текстовое поле
# вместо новой колонки — семантически last_error и так "последняя замеченная
# проблема", а не обязательно окончательный провал.
_MISSING_MARKER = "__poll_stuck_missing_on_paddleocr_vl_service__"


def was_missing_on_last_poll(job_id: str) -> bool:
    with SessionLocal() as session:
        row = session.execute(
            select(ExtractionJob.last_error).where(ExtractionJob.id == job_id)
        ).scalar_one_or_none()
        return row == _MISSING_MARKER


def mark_missing_on_poll(job_id: str) -> None:
    # updated_at сдвигается вперёд намеренно — даёт job ещё один полный
    # STUCK_EXTRACTION_JOB_THRESHOLD_SECONDS цикл на подтверждение реальной
    # пропажи, вместо провала по единственному кратковременному 404.
    with SessionLocal() as session:
        session.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id == job_id)
            .values(last_error=_MISSING_MARKER, updated_at=datetime.utcnow())
        )
        session.commit()


def clear_missing_marker(job_id: str) -> None:
    with SessionLocal() as session:
        session.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id == job_id)
            .where(ExtractionJob.last_error == _MISSING_MARKER)
            .values(last_error=None)
        )
        session.commit()


def mark_job_succeeded(job_id: str) -> None:
    with SessionLocal() as session:
        session.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id == job_id)
            .values(
                status="succeeded",
                updated_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
        )
        session.commit()
