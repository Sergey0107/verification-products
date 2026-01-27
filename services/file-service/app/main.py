from fastapi import FastAPI

app = FastAPI(title="file-service")

@app.get("/health")
async def health():
    return {"status": "ok"}
