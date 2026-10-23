from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import DbSession, require_role
from app.models.user import Role, User
from app.schemas.dashboard import Dashboard, DashboardQuery
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/admin", response_model=Dashboard)
async def team_dashboard(
    q: Annotated[DashboardQuery, Query()],
    user: Annotated[User, Depends(require_role(Role.admin, Role.manager))],
    db: DbSession,
) -> Dashboard:
    """Whole team: for admins and managers."""
    return await build_dashboard(db, user, q, mine=False)


@router.get("/executive", response_model=Dashboard)
async def my_dashboard(
    q: Annotated[DashboardQuery, Query()],
    user: Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))],
    db: DbSession,
) -> Dashboard:
    """Only the signed-in person's own leads, follow-ups, calls and visits."""
    return await build_dashboard(db, user, q, mine=True)
