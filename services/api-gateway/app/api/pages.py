from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user_optional
from app.api.analyses import build_analysis_items
from app.db.models.users import User
from app.db.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    current_user = await get_current_user_optional(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    items = await build_analysis_items(db)
    return templates.TemplateResponse(
        "index.html", {"request": request, "items": items, "user": current_user}
    )


@router.get("/login")
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


@router.get("/register")
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


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response
