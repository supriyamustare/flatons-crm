from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.security import hash_password
from app.models.user import Role, User


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email.lower()))


async def create_user(
    db: AsyncSession, *, email: str, full_name: str, role: Role, password: str
) -> User:
    """Add a user to the session (caller commits). Raises ValueError if the email is taken."""
    if await get_by_email(db, email):
        raise ValueError("A user with this email already exists")
    user = User(
        email=email.lower(),
        full_name=full_name,
        role=role,
        hashed_password=await run_in_threadpool(hash_password, password),
    )
    db.add(user)
    await db.flush()
    return user


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.scalars(select(User).order_by(User.is_active.desc(), User.full_name))
    return list(result)
