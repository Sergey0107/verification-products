import httpx

from app.celery_app import celery_app
from app.core.config import settings
from app.services.compare_service import CompareParseError, compare_json


@celery_app.task(
    bind=True,
    name="domain_analyze.compare_documents",
    queue="domain_analyze",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def compare_documents(
    self,
    job_id: str,
    analysis_id: str,
    tz_data: dict,
    passport_data: dict,
) -> None:
    try:
        result = compare_json(tz_data, passport_data)
        payload = {
            "job_id": job_id,
            "analysis_id": analysis_id,
            "status": "succeeded",
            "result": result,
        }
    except Exception as exc:
        raw = exc.raw if isinstance(exc, CompareParseError) else None
        payload = {
            "job_id": job_id,
            "analysis_id": analysis_id,
            "status": "failed",
            "error": str(exc),
            "raw": raw,
        }
        raise
    finally:
        with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
            client.post(f"{settings.API_GATEWAY_URL}/compare/callback", json=payload)
