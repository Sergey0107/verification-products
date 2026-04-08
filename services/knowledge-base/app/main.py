import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes import router
from app.core.config import settings
from app.db.migrations import bootstrap_data, create_schema
from app.db.session import ping_db


logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("knowledge_base")


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    if settings.KNOWLEDGE_BASE_BOOTSTRAP:
        bootstrap_data()
    logger.info("Knowledge base started")
    yield


app = FastAPI(title=settings.APP_TITLE, lifespan=lifespan)
app.include_router(router)


@app.get("/")
async def index():
    return RedirectResponse(url="/admin/recalculation", status_code=302)


@app.get("/health")
async def health() -> dict[str, str]:
    ping_db()
    return {"status": "ok"}
