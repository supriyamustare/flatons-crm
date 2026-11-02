import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

from app.core.deps import DbSession, require_role
from app.models.user import Role, User
from app.schemas.report import (
    CallsReport,
    CampaignsReport,
    ConversionReport,
    ReportKind,
    ReportQuery,
    StaffReport,
    VisitsReport,
)
from app.services import reports as svc
from app.services.audit import log_audit

router = APIRouter(prefix="/reports", tags=["reports"])
Sales = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]
Q = Annotated[ReportQuery, Query()]


@router.get("/calls", response_model=CallsReport)
async def calls(q: Q, user: Sales, db: DbSession) -> CallsReport:
    return await svc.calls_report(db, user, q)


@router.get("/visits", response_model=VisitsReport)
async def visits(q: Q, user: Sales, db: DbSession) -> VisitsReport:
    return await svc.visits_report(db, user, q)


@router.get("/conversion", response_model=ConversionReport)
async def conversion(q: Q, user: Sales, db: DbSession) -> ConversionReport:
    return await svc.conversion_report(db, user, q)


@router.get("/campaigns", response_model=CampaignsReport)
async def campaigns(q: Q, user: Manager, db: DbSession) -> CampaignsReport:
    """Marketing spend is for admins and managers only."""
    return await svc.campaigns_report(db, user, q)


@router.get("/staff", response_model=StaffReport)
async def staff(q: Q, user: Sales, db: DbSession) -> StaffReport:
    return await svc.staff_report(db, user, q)


def _fmt(v) -> str:
    if v is None:
        return "N/A"
    return str(v)


def _pct(v) -> str:
    return "N/A" if v is None else f"{v * 100:.1f}%"


def _name(u) -> str:
    return u.full_name if u else "Unassigned"


async def _csv_rows(kind: str, db, user, q) -> list[list[str]]:
    if kind == "calls":
        r = await svc.calls_report(db, user, q)
        rows = [["Person", "Calls", "Connected", "Connection rate", "Talk time (min)"]]
        rows += [
            [_name(x.user), x.calls, x.connected, _pct(x.connection_rate), x.talk_minutes]
            for x in [*r.rows, r.totals]
        ]
        rows[-1][0] = "Total"
    elif kind == "visits":
        r = await svc.visits_report(db, user, q)
        head = [
            "Visits",
            "Completed",
            "No-show",
            "Cancelled",
            "Awaiting outcome",
            "Completion rate",
        ]

        def vals(x):
            return [
                x.visits,
                x.completed,
                x.no_show,
                x.cancelled,
                x.scheduled,
                _pct(x.completion_rate),
            ]

        rows = [
            ["By project", *head],
            *[[x.project.name, *vals(x)] for x in r.by_project],
            [],
            ["By visit source", *head],
            *[[x.source.value, *vals(x)] for x in r.by_source],
            [],
            ["By person", *head],
            *[[_name(x.user), *vals(x)] for x in r.by_person],
            [],
            ["Total", *vals(r.totals)],
        ]
    elif kind == "conversion":
        r = await svc.conversion_report(db, user, q)
        head = [
            "Leads",
            "Visited",
            "Booked",
            "Booked after visit",
            "Visit rate",
            "Visit to booking",
            "Conversion rate",
        ]

        def vals(x):
            return [
                x.leads,
                x.visited,
                x.booked,
                x.booked_after_visit,
                _pct(x.visit_rate),
                _pct(x.visit_to_booking_rate),
                _pct(x.conversion_rate),
            ]

        rows = [
            ["By person", *head],
            *[[_name(x.user), *vals(x)] for x in r.by_person],
            [],
            ["By project", *head],
            *[[x.project.name if x.project else "No project", *vals(x)] for x in r.by_project],
            [],
            ["Total", *vals(r.totals)],
        ]
    elif kind == "campaigns":
        r = await svc.campaigns_report(db, user, q)
        rows = [
            [
                "Campaign",
                "Channel",
                "Spend (₹)",
                "Leads",
                "Visited",
                "Booked",
                "Cost per lead (₹)",
                "Cost per visit (₹)",
                "Cost per booking (₹)",
            ]
        ]
        rows += [
            [
                x.name,
                x.channel.value if x.channel else "",
                x.spend,
                x.leads,
                x.visited,
                x.booked,
                _fmt(x.cost_per_lead),
                _fmt(x.cost_per_visit),
                _fmt(x.cost_per_booking),
            ]
            for x in [*r.rows, r.totals]
        ]
        rows.append(["Leads with no campaign", "", "", r.unattributed_leads])
    else:
        r = await svc.staff_report(db, user, q)
        rows = [
            [
                "Person",
                "Leads",
                "Calls",
                "Connected",
                "Connection rate",
                "Visits completed",
                "Bookings",
                "Lead to booking",
            ]
        ]
        rows += [
            [
                x.user.full_name,
                x.leads,
                x.calls,
                x.connected,
                _pct(x.connection_rate),
                x.visits_completed,
                x.bookings,
                _pct(x.lead_to_booking_rate),
            ]
            for x in [*r.rows, r.totals]
        ]
    period = [[f"Flatons CRM: {kind} report", f"{r.date_from} to {r.date_to}"], []]
    return period + [[str(c) for c in row] for row in rows]


@router.get("/{kind}/export")
async def export_csv(
    kind: ReportKind, q: Q, request: Request, user: Manager, db: DbSession
) -> Response:
    """CSV download for admins and managers (executives can view reports but not export)."""
    if kind not in ("calls", "visits", "conversion", "campaigns", "staff"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report")
    rows = await _csv_rows(kind, db, user, q)
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    log_audit(
        db,
        action="report.export",
        entity_type="report",
        entity_id=kind,
        actor=user,
        details=q.model_dump(mode="json", exclude_none=True),
        request=request,
    )
    await db.commit()
    start, end = rows[0][1].split(" to ")
    # The BOM lets Excel open the file as UTF-8 (₹ and names display correctly)
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="flatons-{kind}-{start}-to-{end}.csv"',
            "Cache-Control": "private, no-store",
        },
    )
