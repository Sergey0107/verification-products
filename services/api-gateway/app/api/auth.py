from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    generate_secret_token,
    get_password_hash,
    hash_secret_token,
    verify_password,
)
from app.db.models.users import User, UserSession
from app.db.session import get_db
from app.schemas.user import LoginRequest, LoginResponse, UserCreate, UserPublic

router = APIRouter()
MIN_PASSWORD_LENGTH = 8

SAFE_COOKIE_DELETE_KWARGS = {
    "path": "/",
    "domain": settings.COOKIE_DOMAIN,
    "samesite": settings.COOKIE_SAMESITE,
    "secure": settings.COOKIE_SECURE,
}


def _public_user(user: User) -> UserPublic:
    return UserPublic(id=user.id, login=user.login, created_at=user.created_at)


def _validate_password_or_raise(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _session_expiry() -> datetime:
    return datetime.utcnow() + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)


async def _get_user_from_session_cookie(request: Request, db: AsyncSession) -> User | None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None

    now = datetime.utcnow()
    result = await db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == hash_secret_token(token))
        .where(UserSession.revoked_at.is_(None))
        .where(UserSession.expires_at > now)
    )
    row = result.one_or_none()
    if row is None:
        return None

    session, user = row
    if not session.last_seen_at or (now - session.last_seen_at).total_seconds() > 60:
        await db.execute(
            update(UserSession)
            .where(UserSession.id == session.id)
            .values(last_seen_at=now)
        )
        await db.commit()
    return user


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user_optional(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    return user


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    return await _get_user_from_session_cookie(request, db)


async def create_user_session(
    *,
    user: User,
    request: Request,
    response: Response,
    db: AsyncSession,
) -> str:
    session_token = generate_secret_token()
    csrf_token = generate_secret_token()
    session = UserSession(
        user_id=user.id,
        token_hash=hash_secret_token(session_token),
        csrf_token_hash=hash_secret_token(csrf_token),
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
        expires_at=_session_expiry(),
    )
    db.add(session)
    await db.commit()

    max_age = settings.SESSION_EXPIRE_MINUTES * 60
    cookie_kwargs = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "max_age": max_age,
        "path": "/",
        "domain": settings.COOKIE_DOMAIN,
    }
    response.set_cookie(settings.SESSION_COOKIE_NAME, session_token, **cookie_kwargs)
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=max_age,
        path="/",
        domain=settings.COOKIE_DOMAIN,
    )
    response.delete_cookie("access_token", **SAFE_COOKIE_DELETE_KWARGS)
    return csrf_token


async def revoke_current_session(
    request: Request,
    response: Response,
    db: AsyncSession,
) -> None:
    session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_token:
        await db.execute(
            update(UserSession)
            .where(UserSession.token_hash == hash_secret_token(session_token))
            .where(UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.utcnow())
        )
        await db.commit()

    response.delete_cookie(settings.SESSION_COOKIE_NAME, **SAFE_COOKIE_DELETE_KWARGS)
    response.delete_cookie(settings.CSRF_COOKIE_NAME, **SAFE_COOKIE_DELETE_KWARGS)
    response.delete_cookie("access_token", **SAFE_COOKIE_DELETE_KWARGS)


async def validate_csrf(request: Request, db: AsyncSession) -> bool:
    session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
    csrf_header = request.headers.get("x-csrf-token")
    if not session_token or not csrf_cookie or not csrf_header:
        return False
    if csrf_cookie != csrf_header:
        return False

    result = await db.execute(
        select(UserSession.id)
        .where(UserSession.token_hash == hash_secret_token(session_token))
        .where(UserSession.csrf_token_hash == hash_secret_token(csrf_cookie))
        .where(UserSession.revoked_at.is_(None))
        .where(UserSession.expires_at > datetime.utcnow())
    )
    return result.scalar_one_or_none() is not None


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    _validate_password_or_raise(payload.password)
    result = await db.execute(select(User).where(User.login == payload.login))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Login already exists")

    user = User(login=payload.login, password_hash=get_password_hash(payload.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _public_user(user)


@router.post("/login", response_model=LoginResponse)
async def login_user(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.login == payload.login))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid login or password")

    csrf_token = await create_user_session(
        user=user,
        request=request,
        response=response,
        db=db,
    )
    return LoginResponse(user=_public_user(user), csrf_token=csrf_token)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    await revoke_current_session(request, response, db)
    return {"ok": True}


@router.get("/csrf")
async def read_csrf_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(
        select(UserSession)
        .where(UserSession.token_hash == hash_secret_token(session_token))
        .where(UserSession.revoked_at.is_(None))
        .where(UserSession.expires_at > datetime.utcnow())
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    csrf_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
    if not csrf_token or hash_secret_token(csrf_token) != session.csrf_token_hash:
        csrf_token = generate_secret_token()
        session.csrf_token_hash = hash_secret_token(csrf_token)
        await db.commit()
        response.set_cookie(
            settings.CSRF_COOKIE_NAME,
            csrf_token,
            httponly=False,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=settings.SESSION_EXPIRE_MINUTES * 60,
            path="/",
            domain=settings.COOKIE_DOMAIN,
        )
    return {"csrf_token": csrf_token}


@router.get("/me", response_model=UserPublic)
async def read_me(current_user: User = Depends(get_current_user)):
    return _public_user(current_user)
