import httpx
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="api-gateway")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/")
async def index(request: Request):
    items = [
        {
            "tz": "Разработка модуля авторизации",
            "passport": "Модуль аутентификации v1.0",
            "status": "в процессе",
            "status_key": "in-progress",
        },
        {
            "tz": "Интеграция с внешней СУБД",
            "passport": "Модуль интеграции данных X2.1",
            "status": "готово",
            "status_key": "ready",
        },
        {
            "tz": "Разработка UI для админ-панели",
            "passport": "Административная панель v1.0",
            "status": "в процессе",
            "status_key": "in-progress",
        },
    ]
    return templates.TemplateResponse("index.html", {"request": request, "items": items})

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/file-service/health")
async def ping_file_service():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://file-service:8000/health")
        return response.json()
