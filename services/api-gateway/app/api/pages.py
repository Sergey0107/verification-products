from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user_optional
from app.api.analyses import build_analysis_items, _status_key, _status_label
from app.db.models.analysis import Analysis, ComparisonRow, UserEdit
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


@router.get("/analyses/{analysis_id}")
async def analysis_detail(analysis_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        return RedirectResponse(url="/", status_code=302)

    rows_result = await db.execute(
        select(ComparisonRow).where(ComparisonRow.analysis_id == analysis.id)
    )
    rows = rows_result.scalars().all()
    comment_map: dict[object, str] = {}
    if rows:
        row_ids = [row.id for row in rows]
        latest_subq = (
            select(
                UserEdit.comparison_row_id,
                func.max(UserEdit.edited_at).label("edited_at"),
            )
            .where(UserEdit.comparison_row_id.in_(row_ids))
            .group_by(UserEdit.comparison_row_id)
            .subquery()
        )
        latest_comments = await db.execute(
            select(UserEdit.comparison_row_id, UserEdit.comment).join(
                latest_subq,
                (UserEdit.comparison_row_id == latest_subq.c.comparison_row_id)
                & (UserEdit.edited_at == latest_subq.c.edited_at),
            )
        )
        comment_map = {
            row_id: (comment or "") for row_id, comment in latest_comments.all()
        }

    processing_seconds = None
    if analysis.created_at and analysis.updated_at:
        processing_seconds = int((analysis.updated_at - analysis.created_at).total_seconds())

    return templates.TemplateResponse(
        "analysis_detail.html",
        {
            "request": request,
            "analysis": analysis,
            "rows": rows,
            "status_label": _status_label(analysis.status),
            "status_key": _status_key(analysis.status),
            "processing_seconds": processing_seconds,
            "comment_map": comment_map,
        },
    )
