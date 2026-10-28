from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import DbSession, require_role
from app.models.user import Role, User
from app.schemas.dashboard import Dashboard, DashboardQuery
from app.schemas.insights import Insights
from app.schemas.overview import LeadTab, Overview
from app.services.dashboard import build_dashboard
from app.services.insights import build_insights
from app.services.overview import build_overview

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


@router.get("/overview", response_model=Overview)
async def overview(
    user: Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))],
    db: DbSession,
    person_id: Annotated[
        int | None, Query(description="One person's figures (executives: always their own)")
    ] = None,
    tab: Annotated[LeadTab, Query()] = "fresh",
) -> Overview:
    return await build_overview(db, user, person_id=person_id, tab=tab)


@router.get("/insights", response_model=Insights)
async def insights(
    user: Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))],
    db: DbSession,
    person_id: Annotated[int | None, Query()] = None,
) -> Insights:
    """Projects, lead status, first contact, schedule, 12 months, sources and recent bookings."""
    return await build_insights(db, user, person_id=person_id)
