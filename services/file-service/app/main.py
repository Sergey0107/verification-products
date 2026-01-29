from fastapi import FastAPI

from app.api.routes import router as file_router

app = FastAPI(title="file-service")
app.include_router(file_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
