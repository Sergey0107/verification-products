import httpx
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user_optional, router as auth_router
from app.db.models.analysis import Analysis
from app.db.models.files import File as FileModel
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
    "/files/callback",
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


@app.post("/files/upload")
async def upload_files(
    tz_file: UploadFile = File(...),
    passport_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    analysis = Analysis(status="uploading")
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)

    tz_key = f"tz/{uuid4()}_{tz_file.filename}"
    passport_key = f"passport/{uuid4()}_{passport_file.filename}"

    tz_record = FileModel(
        analysis_id=analysis.id,
        file_type="tz",
        original_name=tz_file.filename or "",
        storage_path=tz_key,
        status="uploading",
    )
    passport_record = FileModel(
        analysis_id=analysis.id,
        file_type="passport",
        original_name=passport_file.filename or "",
        storage_path=passport_key,
        status="uploading",
    )
    db.add_all([tz_record, passport_record])
    await db.flush()
    await db.refresh(tz_record)
    await db.refresh(passport_record)
    await db.commit()

    async with httpx.AsyncClient() as client:
        files = {
            "tz_file": (tz_file.filename, await tz_file.read(), tz_file.content_type),
            "passport_file": (
                passport_file.filename,
                await passport_file.read(),
                passport_file.content_type,
            ),
        }
        data = {
            "analysis_id": str(analysis.id),
            "tz_file_id": str(tz_record.id),
            "passport_file_id": str(passport_record.id),
            "tz_key": tz_key,
            "passport_key": passport_key,
        }
        response = await client.post(
            "http://file-service:8000/files/upload-batch", files=files, data=data
        )
        response.raise_for_status()
        return response.json()


@app.post("/files/callback")
async def files_callback(payload: dict, db: AsyncSession = Depends(get_db)):
    try:
        file_id = UUID(payload.get("file_id"))
        analysis_id = UUID(payload.get("analysis_id"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ids")

    status_value = payload.get("status")
    if status_value not in {"uploaded", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    values = {"status": status_value}
    if status_value == "uploaded":
        values.update(
            {
                "storage_path": payload.get("storage_path"),
                "mime_type": payload.get("mime_type"),
                "size_bytes": payload.get("size_bytes"),
                "uploaded_at": datetime.utcnow(),
            }
        )

    await db.execute(
        update(FileModel)
        .where(FileModel.id == file_id)
        .where(FileModel.analysis_id == analysis_id)
        .values(**values)
    )
    await db.commit()

    result = await db.execute(
        select(func.count(FileModel.id)).where(
            FileModel.analysis_id == analysis_id, FileModel.status == "uploaded"
        )
    )
    if (result.scalar_one() or 0) >= 2:
        await db.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(status="ready", updated_at=datetime.utcnow())
        )
        await db.commit()

    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/file-service/health")
async def ping_file_service():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://file-service:8000/health")
        return response.json()
