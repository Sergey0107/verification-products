from fastapi import FastAPI

from app.api.routes import router as prompts_router

app = FastAPI(title="prompt-registry", version="0.1.0")

app.include_router(prompts_router)
