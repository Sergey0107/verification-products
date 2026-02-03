from fastapi import FastAPI

from app.api.routes import router as compare_router

app = FastAPI(title="domain-analyze", version="0.1.0")

app.include_router(compare_router)
