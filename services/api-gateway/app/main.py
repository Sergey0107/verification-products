import httpx
from fastapi import FastAPI

app = FastAPI(title="api-gateway")

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/file-service/health")
async def ping_file_service():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://file-service:8000/health")
        return response.json()