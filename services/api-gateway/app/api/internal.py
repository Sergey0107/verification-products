"""Внутренние эндпоинты для сервис-к-сервису колбэков — не предназначены для
прямого вызова клиентом/фронтендом (нет auth-middleware обычных /api
маршрутов, только доверие к внутренней docker-сети)."""

from fastapi import APIRouter, HTTPException

from app.services.extraction_jobs import find_job_by_external_id
from app.tasks import finalize_extraction_task

router = APIRouter()


@router.post("/internal/extraction-callback")
async def extraction_callback(payload: dict):
    """Принимает финальный статус async-job'а от paddleocr-vl-service (см.
    job_queue.py._deliver_callback там) — job запускается из extract_file
    (app/tasks.py) для backend=yandex_vision_ocr, когда извлечение слишком
    долгое для одного синхронного HTTP-запроса (большие документы, облачный
    OCR+LLM пайплайн, см. обсуждение архитектурной проблемы ReadTimeout).

    Тело: {"job_id": "<external_job_id>", "status": "succeeded"|"failed",
    "result": {...} | None, "error": str | None}.

    Реальная работа (сохранение результата, продвижение конвейера анализа)
    делегируется Celery-задаче finalize_extraction_task — этот эндпоинт
    только сопоставляет external_job_id с extraction_job и ставит задачу в
    очередь, отвечая как можно быстрее (paddleocr-vl-service ретраит
    доставку callback самостоятельно при недоставке, лишняя задержка здесь
    увеличивает окно для гонки/таймаута на его стороне)."""
    external_job_id = payload.get("job_id")
    status_value = payload.get("status")
    if not external_job_id or status_value not in {"succeeded", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid callback payload: expected job_id and status")

    job = find_job_by_external_id(external_job_id)
    if job is None:
        # Не 5xx: paddleocr-vl-service ретраит callback при ЛЮБОЙ ошибке
        # (см. CALLBACK_MAX_ATTEMPTS в job_queue.py) — если extraction_job с
        # таким external_job_id реально не существует (например TTL
        # чекпоинта истёк на нашей стороне раньше, чем там завершился job —
        # маловероятно, но не невозможно), повторные попытки ничего не
        # изменят. 404 сообщает вызывающей стороне остановить ретраи.
        raise HTTPException(status_code=404, detail=f"No extraction_job found for external_job_id={external_job_id}")

    finalize_extraction_task.delay(
        job_id=job["id"],
        analysis_id=job["analysis_id"],
        file_id=job["file_id"],
        file_type=job["file_type"],
        # extraction_backend не хранится на extraction_job — но для async-
        # пути он всегда yandex_vision_ocr (единственный backend, который
        # запускает async job'ы, см. run_extraction_task).
        extraction_backend="yandex_vision_ocr",
        status=status_value,
        result_payload=payload.get("result"),
        error=payload.get("error"),
    )
    return {"ok": True}
