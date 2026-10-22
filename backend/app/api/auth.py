from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.deps import ACCESS_COOKIE, REFRESH_COOKIE, DbSession, user_from_token
from app.core.security import create_token, dummy_hash, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.schemas.user import UserOut
from app.services import users as users_service
from app.services.audit import log_audit

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_PATH = "/api"
REFRESH_PATH = "/api/auth"


def set_auth_cookies(response: Response, user: User) -> None:
    """Issue fresh access + refresh tokens as HttpOnly cookies."""
    settings = get_settings()
    access_ttl = timedelta(minutes=settings.access_token_expire_minutes)
    refresh_ttl = timedelta(days=settings.refresh_token_expire_days)
    cookie = {"httponly": True, "secure": settings.secure_cookies, "samesite": "lax"}

    response.set_cookie(
        ACCESS_COOKIE,
        create_token(
            user_id=user.id,
            token_version=user.token_version,
            token_type="access",
            expires_in=access_ttl,
        ),
        max_age=int(access_ttl.total_seconds()),
        path=ACCESS_PATH,
        **cookie,
    )
    # The refresh cookie is only ever sent to /api/auth/*, never to other endpoints.
    response.set_cookie(
        REFRESH_COOKIE,
        create_token(
            user_id=user.id,
            token_version=user.token_version,
            token_type="refresh",
            expires_in=refresh_ttl,
        ),
        max_age=int(refresh_ttl.total_seconds()),
        path=REFRESH_PATH,
        **cookie,
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    cookie = {"httponly": True, "secure": settings.secure_cookies, "samesite": "lax"}
    response.delete_cookie(ACCESS_COOKIE, path=ACCESS_PATH, **cookie)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, **cookie)


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, request: Request, response: Response, db: DbSession) -> User:
    user = await users_service.get_by_email(db, body.email)
    hashed = user.hashed_password if user else dummy_hash()
    password_ok = await run_in_threadpool(verify_password, body.password, hashed)

    if user is None or not password_ok or not user.is_active:
        reason = (
            "unknown_email" if user is None else ("bad_password" if not password_ok else "inactive")
        )
        log_audit(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            details={"email": body.email, "reason": reason},
            request=request,
        )
        await db.commit()
        # Same message for every failure so attackers can't tell which emails exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    user.last_login_at = datetime.now(UTC)
    log_audit(
        db, action="auth.login", entity_type="user", entity_id=user.id, actor=user, request=request
    )
    await db.commit()
    await db.refresh(user)

    set_auth_cookies(response, user)
    return user


@router.post("/refresh", response_model=UserOut)
async def refresh(request: Request, response: Response, db: DbSession) -> User:
    user = await user_from_token(db, request.cookies.get(REFRESH_COOKIE), "refresh")
    set_auth_cookies(response, user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    clear_auth_cookies(response)
