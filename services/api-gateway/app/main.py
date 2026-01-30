from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import get_current_user_optional, router as auth_router
from app.api.pages import router as pages_router
from app.api.files import router as files_router
from app.api.analyses import router as analyses_router
from app.api.health import router as health_router
from app.db.session import AsyncSessionLocal

app = FastAPI(title="api-gateway")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(pages_router, tags=["pages"])
app.include_router(files_router, tags=["files"])
app.include_router(analyses_router, prefix="/api", tags=["analyses"])
app.include_router(health_router, tags=["health"])

ALLOWED_PATHS = {
    "/",
    "/login",
    "/register",
    "/logout",
    "/auth/login",
    "/auth/login/form",
    "/auth/register",
    "/auth/register/form",
    "/files/callback",
    "/health",
    "/file-service/health",
}
ALLOWED_STATIC = {"/static/css/login.css", "/static/css/register.css"}


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if path in ALLOWED_PATHS or path in ALLOWED_STATIC:
        return await call_next(request)
    async with AsyncSessionLocal() as db:
        user = await get_current_user_optional(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return await call_next(request)
