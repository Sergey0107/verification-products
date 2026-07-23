import logging
import time
import traceback

import httpx

from app.celery_app import celery_app
from app.core.config import settings
from app.services.compare_service import CompareParseError, compare_json

logger = logging.getLogger(__name__)


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
    log_extra = {"analysis_id": analysis_id, "job_id": job_id}
    started_at = time.monotonic()
    tz_product_count = len((tz_data or {}).get("products") or [])
    passport_product_count = len((passport_data or {}).get("products") or [])
    logger.info(
        "compare_documents started: attempt=%s tz_products=%s passport_products=%s",
        self.request.retries + 1, tz_product_count, passport_product_count,
        extra={**log_extra, "step": "compare_documents_start"},
    )
    payload: dict | None = None
    try:
        result = compare_json(tz_data, passport_data)
        payload = {
            "job_id": job_id,
            "analysis_id": analysis_id,
            "status": "succeeded",
            "result": result,
        }
        logger.info(
            "compare_documents succeeded in %.2fs: comparisons=%s match=%s",
            time.monotonic() - started_at,
            len(result.get("comparisons") or []), result.get("match"),
            extra={**log_extra, "step": "compare_documents_finished"},
        )
    except Exception as exc:
        error_detail = "".join(
            [
                str(exc),
                "\n\nDomain analyze worker traceback:\n",
                traceback.format_exc(),
            ]
        )
        logger.exception(
            "Comparison task failed: analysis_id=%s job_id=%s attempt=%s elapsed=%.2fs",
            analysis_id,
            job_id,
            self.request.retries + 1,
            time.monotonic() - started_at,
            extra={**log_extra, "step": "compare_documents_failed"},
        )
        raw = exc.raw if isinstance(exc, CompareParseError) else None
        payload = {
            "job_id": job_id,
            "analysis_id": analysis_id,
            "status": "failed",
            "error": error_detail,
            "raw": raw,
        }
        raise
    finally:
        if payload is not None:
            try:
                with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
                    client.post(f"{settings.API_GATEWAY_URL}/compare/callback", json=payload)
            except Exception:
                logger.exception(
                    "compare_documents: failed to deliver callback to api-gateway "
                    "(comparison status=%s will not reach the analysis record)",
                    payload.get("status"),
                    extra={**log_extra, "step": "compare_documents_callback_failed"},
                )
                raise
