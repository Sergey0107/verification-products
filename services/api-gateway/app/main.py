from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.analyses import router as analyses_router
from app.api.auth import get_current_user_optional, router as auth_router, validate_csrf
from app.api.compare import router as compare_router
from app.api.comparison_rows import router as comparison_rows_router
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal

app = FastAPI(title="api-gateway")
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(files_router, tags=["files"])
app.include_router(analyses_router, prefix="/api", tags=["analyses"])
app.include_router(comparison_rows_router, prefix="/api", tags=["comparison-rows"])
app.include_router(compare_router, tags=["compare"])
app.include_router(health_router, tags=["health"])

ALLOWED_PATHS = {
    "/auth/login",
    "/auth/register",
    "/files/callback",
    "/compare/callback",
    "/health",
    "/file-service/health",
}
CSRF_EXEMPT_PATHS = {
    "/auth/login",
    "/auth/register",
    "/files/callback",
    "/compare/callback",
    "/health",
    "/file-service/health",
}
CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
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
