from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "file_service",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_default_queue="file_service",
    task_default_exchange="file_service",
    task_default_routing_key="file_service",
    task_queues={
        "file_service": {
            "exchange": "file_service",
            "routing_key": "file_service",
        },
    },
    task_routes={
        "file_service.upload_to_s3": {
            "queue": "file_service",
            "routing_key": "file_service",
        },
    },
)
