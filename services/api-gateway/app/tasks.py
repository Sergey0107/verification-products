from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.celery_app import celery_app
from app.core.config import settings
from app.db.models.comparison_jobs import ComparisonJob
from app.db.models.extraction_results import ExtractionResult
from app.db.session_sync import SessionLocal
from app.services.comp_data import update_comp_data
from app.services.extraction_jobs import (
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from app.services.extraction_tasks import run_extraction_task


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
) -> None:
    attempt = self.request.retries + 1
    mark_job_running(job_id, attempt)
    try:
        result_payload = run_extraction_task(
            analysis_id=analysis_id,
            file_id=file_id,
            file_type=file_type,
            storage_path=storage_path,
            storage_url=storage_url,
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

            if "tz" in by_type and "passport" in by_type:
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
                    payload = {
                        "job_id": str(compare_job_id),
                        "analysis_id": analysis_id,
                        "tz_data": by_type["tz"],
                        "passport_data": by_type["passport"],
                    }
                    with httpx.Client(timeout=settings.EXTRACTION_TIMEOUT_SECONDS) as client:
                        client.post(
                            f"{settings.DOMAIN_ANALYZE_URL}/compare/jobs",
                            json=payload,
                        )
    except Exception as exc:
        status = "failed" if self.request.retries >= self.max_retries else "retrying"
        mark_job_failed(job_id, str(exc), status)
        update_comp_data(
            "extraction",
            {
                "analysis_id": analysis_id,
                "status": status,
                "error": str(exc),
                "file_type": file_type,
            },
        )
        raise
    else:
        mark_job_succeeded(job_id)
