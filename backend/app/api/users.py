from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool

from app.api.auth import set_auth_cookies
from app.core.deps import CurrentUser, DbSession, require_role
from app.core.security import hash_password, verify_password
from app.models.user import Role, User
from app.schemas.user import PasswordChange, UserCreate, UserOut, UserUpdate
from app.services import users as users_service
from app.services.audit import log_audit

router = APIRouter(prefix="/users", tags=["users"])

AdminUser = Annotated[User, Depends(require_role(Role.admin))]


async def _get_user_or_404(db: DbSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


# ---- Current user ---------------------------------------------------------


@router.get("/me", response_model=UserOut)
async def read_me(user: CurrentUser) -> User:
    return user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    body: PasswordChange, request: Request, response: Response, user: CurrentUser, db: DbSession
) -> None:
    if not await run_in_threadpool(verify_password, body.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")

    user.hashed_password = await run_in_threadpool(hash_password, body.new_password)
    user.token_version += 1  # signs out every other device
    log_audit(
        db,
        action="user.password_change",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    set_auth_cookies(response, user)  # keep this device signed in


# ---- Admin: user management ----------------------------------------------


@router.get("", response_model=list[UserOut])
async def list_users(_: AdminUser, db: DbSession) -> list[User]:
    return await users_service.list_users(db)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, request: Request, admin: AdminUser, db: DbSession) -> User:
    try:
        user = await users_service.create_user(
            db, email=body.email, full_name=body.full_name, role=body.role, password=body.password
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    log_audit(
        db,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        actor=admin,
        details={"email": user.email, "role": user.role.value},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, _: AdminUser, db: DbSession) -> User:
    return await _get_user_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, body: UserUpdate, request: Request, admin: AdminUser, db: DbSession
) -> User:
    user = await _get_user_or_404(db, user_id)

    if user.id == admin.id and (
        (body.role is not None and body.role != Role.admin) or body.is_active is False
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You can't remove your own admin access or deactivate yourself",
        )

    changes: dict[str, Any] = {}
    if body.full_name is not None and body.full_name != user.full_name:
        changes["full_name"] = {"from": user.full_name, "to": body.full_name}
        user.full_name = body.full_name
    if body.role is not None and body.role != user.role:
        changes["role"] = {"from": user.role.value, "to": body.role.value}
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": body.is_active}
        user.is_active = body.is_active
        if not body.is_active:
            user.token_version += 1
    if body.password is not None:
        changes["password"] = "reset"
        user.hashed_password = await run_in_threadpool(hash_password, body.password)
        user.token_version += 1

    if changes:
        log_audit(
            db,
            action="user.update",
            entity_type="user",
            entity_id=user.id,
            actor=admin,
            details={"changes": changes},
            request=request,
        )
        await db.commit()
        await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(user_id: int, request: Request, admin: AdminUser, db: DbSession) -> None:
    """Deactivate (never hard-delete) a user and sign them out everywhere."""
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't deactivate yourself")
    if not user.is_active:
        return

    user.is_active = False
    user.token_version += 1
    log_audit(
        db,
        action="user.deactivate",
        entity_type="user",
        entity_id=user.id,
        actor=admin,
        request=request,
    )
    await db.commit()
