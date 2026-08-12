import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.logging_setup import configure_logging

configure_logging("api-gateway")

from app.api.analyses import router as analyses_router
from app.api.auth import get_current_user_optional, router as auth_router, validate_csrf
from app.api.compare import router as compare_router
from app.api.comparison_rows import router as comparison_rows_router
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.manual_characteristics import router as manual_characteristics_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal

app = FastAPI(title="api-gateway")
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(files_router, tags=["files"])
app.include_router(analyses_router, prefix="/api", tags=["analyses"])
app.include_router(comparison_rows_router, prefix="/api", tags=["comparison-rows"])
app.include_router(manual_characteristics_router, prefix="/api", tags=["manual-characteristics"])
app.include_router(compare_router, tags=["compare"])
app.include_router(health_router, tags=["health"])
app.include_router(internal_router, tags=["internal"])

ALLOWED_PATHS = {
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
    "/auth/login",
    "/auth/register",
    "/files/callback",
    "/compare/callback",
    "/internal/extraction-callback",
    "/health",
    "/file-service/health",
}
CSRF_EXEMPT_PATHS = {
    "/auth/login",
    "/auth/register",
    "/files/callback",
    "/compare/callback",
    "/internal/extraction-callback",
    "/health",
    "/file-service/health",
}
CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Пути из ALLOWED_PATHS, которые вызываются НЕ браузером, а другими сервисами:
# пользовательской сессии у них нет, поэтому они защищены общим секретом
# (см. INTERNAL_CALLBACK_SECRET). Без этого /files/callback был доступен
# анониму из интернета, т.к. nginx проксирует весь префикс /files/.
INTERNAL_CALLBACK_PATHS = {
    "/files/callback",
    "/compare/callback",
    "/internal/extraction-callback",
}


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if path in INTERNAL_CALLBACK_PATHS:
        expected = settings.INTERNAL_CALLBACK_SECRET
        if expected:
            provided = request.headers.get(settings.INTERNAL_CALLBACK_HEADER, "")
            # compare_digest, а не ==: сравнение секретов должно быть
            # constant-time, иначе по времени ответа секрет подбирается побайтно.
            if not secrets.compare_digest(provided, expected):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)
    if path in ALLOWED_PATHS:
        return await call_next(request)

    async with AsyncSessionLocal() as db:
        user = await get_current_user_optional(request, db)
        uses_session_cookie = settings.SESSION_COOKIE_NAME in request.cookies
        if (
            user is not None
            and uses_session_cookie
            and request.method in CSRF_METHODS
            and path not in CSRF_EXEMPT_PATHS
        ):
            if not await validate_csrf(request, db):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid CSRF token"},
                )

    if user is None:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    return await call_next(request)
