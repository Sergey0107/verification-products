from celery import Celery

from app.logging_setup import configure_logging

configure_logging("api-gateway-worker")

from app.core.config import settings

celery_app = Celery(
    "api_gateway",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    # Подтверждаем задачу только ПОСЛЕ выполнения (а не при получении): если воркер
    # упадёт/перезапустится во время длинного извлечения, задача вернётся в очередь
    # и переобработается, а не потеряется (иначе статус застревает в running).
    # extract_file идемпотентна (результат пишется через on_conflict_do_update).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="api_gateway",
    task_default_exchange="api_gateway",
    task_default_routing_key="api_gateway",
    task_queues={
        "api_gateway": {
            "exchange": "api_gateway",
            "routing_key": "api_gateway",
        },
    },
    task_routes={
        "api_gateway.extract_file": {
            "queue": "api_gateway",
            "routing_key": "api_gateway",
        },
    },
    # Fallback на случай, если callback от paddleocr-vl-service (см.
    # job_queue.py._deliver_callback там, до 6 попыток доставки с backoff)
    # так и не дошёл — например api-gateway был недоступен всё это окно
    # (рестарт/деплой). Каждые 3 минуты проверяем "зависшие" extraction_job
    # (running + есть external_job_id + давно не обновлялись) напрямую через
    # GET {paddleocr}/jobs/{external_job_id} — см. app.tasks.poll_stuck_
    # extraction_jobs. Требует запуска воркера с флагом -B (celery beat
    # встроен в тот же процесс, отдельный сервис не нужен).
    beat_schedule={
        "poll-stuck-extraction-jobs": {
            "task": "api_gateway.poll_stuck_extraction_jobs",
            "schedule": 180.0,
        },
    },
)
