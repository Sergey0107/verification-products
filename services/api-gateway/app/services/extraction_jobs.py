from datetime import datetime

from sqlalchemy import update

from app.db.models.extraction_jobs import ExtractionJob
from app.db.session_sync import SessionLocal


def mark_job_running(job_id: str, attempt: int) -> None:
    with SessionLocal() as session:
        session.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id == job_id)
            .values(
                status="running",
                attempts=attempt,
                updated_at=datetime.utcnow(),
            )
        )
        session.commit()


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
