from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.pipeline import PipelineStage
from app.models.user import Role, User
from app.schemas.pipeline import (
    Forecast,
    PipelineBoard,
    PipelineCard,
    PipelineQuery,
    ProbabilityUpdate,
    StageProbability,
)
from app.services import pipeline as svc
from app.services.audit import log_audit

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
SalesUser = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]
Admin = Annotated[User, Depends(require_role(Role.admin))]


@router.get("", response_model=PipelineBoard)
async def board(
    q: Annotated[PipelineQuery, Query()], user: SalesUser, db: DbSession
) -> PipelineBoard:
    """Leads grouped by stage with count, value and weighted value per stage."""
    return await svc.build_board(db, user, q)


@router.get("/aged", response_model=list[PipelineCard])
async def aged(
    q: Annotated[PipelineQuery, Query()], user: SalesUser, db: DbSession
) -> list[PipelineCard]:
    """Open leads with no activity for 7+ days, longest-stuck first."""
    q.stale_only = True
    b = await svc.build_board(db, user, q)
    cards = [c for col in b.stages for c in col.cards]
    return sorted(cards, key=lambda c: c.last_activity_at)


@router.get("/forecast", response_model=Forecast)
async def forecast(
    q: Annotated[PipelineQuery, Query()], user: SalesUser, db: DbSession
) -> Forecast:
    """Weighted value of open deals by project and by executive."""
    return await svc.build_forecast(db, user, q)


@router.get("/stages", response_model=list[StageProbability])
async def list_stages(_: SalesUser, db: DbSession) -> list[StageProbability]:
    probs = await svc.probabilities(db)
    return [StageProbability(stage=s, probability_pct=p) for s, p in probs.items()]


@router.patch("/stages", response_model=list[StageProbability])
async def update_stages(
    body: ProbabilityUpdate, request: Request, admin: Admin, db: DbSession
) -> list[StageProbability]:
    rows = {s.stage: s for s in await db.scalars(select(PipelineStage))}
    current = await svc.probabilities(db)
    changes = {}
    for item in body.stages:
        row = rows.get(item.stage)
        if row is None:  # stage never saved before: create its row
            row = PipelineStage(stage=item.stage, probability_pct=current[item.stage])
            db.add(row)
        if row.probability_pct != item.probability_pct:
            changes[item.stage.value] = {"from": row.probability_pct, "to": item.probability_pct}
            row.probability_pct = item.probability_pct
    if changes:
        log_audit(
            db,
            action="pipeline.probabilities",
            entity_type="pipeline",
            actor=admin,
            details=changes,
            request=request,
        )
    await db.commit()
    probs = await svc.probabilities(db)
    return [StageProbability(stage=s, probability_pct=p) for s, p in probs.items()]
