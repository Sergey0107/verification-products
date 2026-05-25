from datetime import datetime
import logging
import traceback

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
            extraction_backend=extraction_backend,
            target_characteristics=target_characteristics,
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
                    }
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
            "Extraction task failed: analysis_id=%s file_id=%s file_type=%s job_id=%s attempt=%s status=%s",
            analysis_id,
            file_id,
            file_type,
            job_id,
            attempt,
            status,
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
