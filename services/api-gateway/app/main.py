import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user_optional, router as auth_router
from app.db.models.users import User
from app.db.session import AsyncSessionLocal, get_db

app = FastAPI(title="api-gateway")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
app.include_router(auth_router, prefix="/auth", tags=["auth"])

ALLOWED_PATHS = {
    "/login",
    "/register",
    "/auth/login",
    "/auth/login/form",
    "/auth/register",
    "/auth/register/form",
    "/health",
}
ALLOWED_STATIC = {"/static/css/login.css", "/static/css/register.css"}


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if path in ALLOWED_PATHS or path in ALLOWED_STATIC:
        return await call_next(request)
    if path.startswith("/static"):
        async with AsyncSessionLocal() as db:
            user = await get_current_user_optional(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)
    return await call_next(request)

@app.get("/")
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    current_user = await get_current_user_optional(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
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
    return templates.TemplateResponse(
        "index.html", {"request": request, "items": items, "user": current_user}
    )


@app.get("/login")
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    current_user = await get_current_user_optional(request, db)
    if current_user is not None:
        return RedirectResponse(url="/", status_code=302)
    error_code = request.query_params.get("error")
    error = error_code == "1"
    result = await db.execute(select(func.count(User.id)))
    has_users = (result.scalar_one() or 0) > 0
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error, "show_register": not has_users},
    )


@app.get("/register")
async def register_page(request: Request, db: AsyncSession = Depends(get_db)):
    current_user = await get_current_user_optional(request, db)
    if current_user is not None:
        return RedirectResponse(url="/", status_code=302)
    result = await db.execute(select(func.count(User.id)))
    has_users = (result.scalar_one() or 0) > 0
    if has_users:
        return RedirectResponse(url="/login", status_code=302)
    error_code = request.query_params.get("error")
    error = error_code == "1"
    return templates.TemplateResponse(
        "register.html", {"request": request, "error": error}
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/file-service/health")
async def ping_file_service():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://file-service:8000/health")
        return response.json()
