from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "api_gateway",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
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
)
