"""Test setup. Integration tests need PostgreSQL (docker-compose.dev.yml locally).
The test database (flatons_crm_test) is created automatically and rebuilt every run."""

import asyncio
import os

os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://crmuser:devpassword@localhost:5432/flatons_crm_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-1234567890")
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing in tests only

from collections.abc import AsyncIterator, Awaitable, Callable  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import make_url, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Role, User  # noqa: E402

TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    """Create the test database if needed and build a fresh schema once per run."""

    async def setup() -> None:
        url = make_url(os.environ["TEST_DATABASE_URL"])
        admin = create_async_engine(
            url.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
        )
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
        await admin.dispose()

        test_engine = create_async_engine(url, poolclass=NullPool)
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await test_engine.dispose()

    asyncio.run(setup())


@pytest.fixture(autouse=True)
async def _clean_tables() -> None:
    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.fixture
def make_user(db: AsyncSession) -> Callable[..., Awaitable[User]]:
    counter = {"n": 0}

    async def _make(
        role: Role = Role.executive, *, email: str | None = None, is_active: bool = True
    ) -> User:
        counter["n"] += 1
        user = User(
            email=email or f"{role.value}{counter['n']}@flatons.com",
            full_name=f"Test {role.value.title()} {counter['n']}",
            role=role,
            is_active=is_active,
            hashed_password=hash_password(TEST_PASSWORD),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    return _make


@pytest.fixture
async def login_as(make_user) -> AsyncIterator[Callable[..., Awaitable[tuple[AsyncClient, User]]]]:
    """Create a user and return a separate client already logged in as them."""
    clients: list[AsyncClient] = []

    async def _login(role: Role = Role.executive) -> tuple[AsyncClient, User]:
        user = await make_user(role)
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        clients.append(c)
        resp = await c.post(
            "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
        )
        assert resp.status_code == 200, resp.text
        return c, user

    yield _login
    for c in clients:
        await c.aclose()


async def new_project(db: AsyncSession, name: str = "Flatons Heights", *, resale: bool = False):
    """A valid project: developer projects get a developer (the database requires it)."""
    from app.models import Developer, Project, ProjectType

    developer = None
    if not resale:
        developer = Developer(name=f"{name} Developers")
        db.add(developer)
        await db.flush()
    project = Project(
        name=name,
        project_type=ProjectType.resale if resale else ProjectType.developer,
        developer_id=developer.id if developer else None,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project
