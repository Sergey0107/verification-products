from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "domain_analyze",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    # Подтверждаем задачу только ПОСЛЕ выполнения: если воркер упадёт во время
    # сравнения, задача вернётся в очередь, а не потеряется. compare_documents
    # идемпотентна (результат уходит callback'ом в gateway).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="domain_analyze",
    task_default_exchange="domain_analyze",
    task_default_routing_key="domain_analyze",
    task_queues={
        "domain_analyze": {
            "exchange": "domain_analyze",
            "routing_key": "domain_analyze",
        },
    },
    task_routes={
        "domain_analyze.compare_documents": {
            "queue": "domain_analyze",
            "routing_key": "domain_analyze",
        },
    },
)
