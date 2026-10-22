"""Shared FastAPI dependencies: DB session, current user, role guard."""

from collections.abc import Awaitable, Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import TokenType, decode_token
from app.models.user import Role, User

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"

DbSession = Annotated[AsyncSession, Depends(get_db)]

_unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def user_from_token(db: AsyncSession, token: str | None, token_type: TokenType) -> User:
    """Validate a token and return its active user, or raise 401."""
    if not token:
        raise _unauthorized
    try:
        payload = decode_token(token, token_type)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError):
        raise _unauthorized from None

    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.token_version != payload["ver"]:
        raise _unauthorized
    return user


async def get_current_user(request: Request, db: DbSession) -> User:
    return await user_from_token(db, request.cookies.get(ACCESS_COOKIE), "access")


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: Role) -> Callable[..., Awaitable[User]]:
    """Dependency that allows only the given roles, e.g. Depends(require_role(Role.admin))."""

    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to do this",
            )
        return user

    return checker
