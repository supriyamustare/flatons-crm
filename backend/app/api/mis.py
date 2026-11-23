import csv
import io
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.inventory import Building
from app.models.mis import MisSnapshot
from app.models.project import Project
from app.models.user import Role, User
from app.services import mis
from app.services.audit import log_audit

router = APIRouter(prefix="/mis", tags=["mis"])
MIS_ROLES = (
    Role.admin,
    Role.management,
    Role.crm_manager,
    Role.finance,
    Role.finance_approver,
    Role.auditor,
)
Viewer = Annotated[User, Depends(require_role(*MIS_ROLES))]


def filters(
    project_id: int | None = None,
    building_id: int | None = None,
    owner_id: int | None = None,
    booking_from: date | None = None,
    booking_to: date | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
) -> mis.Filters:
    if (
        period_from
        and period_to
        and period_from > period_to
        or booking_from
        and booking_to
        and booking_from > booking_to
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The 'from' date must be before the 'to' date"
        )
    return mis.Filters(
        project_id, building_id, owner_id, booking_from, booking_to, period_from, period_to
    )


F = Annotated[mis.Filters, Depends(filters)]


@router.get("/options")
async def options(_: Viewer, db: DbSession) -> dict:
    """The filter choices: projects, their towers, and CRM owners."""
    projects = list(await db.scalars(select(Project).order_by(Project.name)))
    buildings = list(await db.scalars(select(Building).order_by(Building.name)))
    owners = list(
        await db.scalars(
            select(User)
            .where(User.is_active.is_(True), User.role.in_([Role.postsales_exec, Role.crm_manager]))
            .order_by(User.full_name)
        )
    )
    return {
        "projects": [{"id": p.id, "name": p.name} for p in projects],
        "buildings": [{"id": b.id, "name": b.name, "project_id": b.project_id} for b in buildings],
        "owners": [{"id": u.id, "name": u.full_name} for u in owners],
        "not_available": mis.NOT_AVAILABLE,
    }


@router.get("/dashboard")
async def dashboard(_: Viewer, db: DbSession, f: F) -> dict:
    return {"as_of": mis.today(), **await mis.dashboard(db, f)}


@router.get("/reports/{section}")
async def reports(
    section: Literal["finance", "operations"], _: Viewer, db: DbSession, f: F
) -> dict:
    data = await (mis.finance(db, f) if section == "finance" else mis.operations(db, f))
    return {"as_of": mis.today(), "period": {"from": f.period_from, "to": f.period_to}, **data}


@router.get("/export/{section}/{report}")
async def export(
    section: Literal["finance", "operations"],
    report: str,
    request: Request,
    user: Viewer,
    db: DbSession,
    f: F,
) -> StreamingResponse:
    """One report's rows as CSV (logged)."""
    data = await (mis.finance(db, f) if section == "finance" else mis.operations(db, f))
    rows = data.get(report)
    if report.startswith("upcoming_"):
        rows = data["upcoming"].get(report.split("_", 1)[1], {}).get("items")
    if not isinstance(rows, list):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such list to export")
    rows = [{k: v for k, v in r.items() if not isinstance(v, (list, dict))} for r in rows]
    buf = io.StringIO()
    cols = list(dict.fromkeys(k for r in rows for k in r)) or ["(no rows)"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    log_audit(
        db,
        action="mis.export",
        entity_type="report",
        entity_id=None,
        actor=user,
        details={"section": section, "report": report, "rows": len(rows)},
        request=request,
    )
    await db.commit()
    name = f"{section}-{report}-{mis.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/snapshots")
async def snapshots(
    _: Viewer,
    db: DbSession,
    project_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    """Historical positions as they stood each night."""
    q = select(MisSnapshot).where(
        MisSnapshot.project_id.is_(None)
        if project_id is None
        else MisSnapshot.project_id == project_id
    )
    if start:
        q = q.where(MisSnapshot.taken_on >= start)
    if end:
        q = q.where(MisSnapshot.taken_on <= end)
    return [
        {"taken_on": s.taken_on, **s.data}
        for s in await db.scalars(q.order_by(MisSnapshot.taken_on.desc()).limit(400))
    ]
