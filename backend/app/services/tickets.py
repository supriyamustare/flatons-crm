"""Ticket rules: default team per category, confirmation rules, SLA targets and their state.

SLA (part 1: fixed targets by priority; part 2 makes them configurable):
  response target   urgent 2 h, high 4 h, normal 1 working day (24 h), low 2 working days
  resolution target urgent 1 day, high 3 days, normal 7 days, low 15 days
  Paused while waiting for the customer or a third party: the resolution target moves out by the paused time, and the
  paused time is kept (customer / external separately) so reports can show it.
  At risk: less than 25% of the resolution window left (or the response due within an hour, not yet acknowledged).
"""

from datetime import UTC, datetime, timedelta

from app.models.ticket import (
    PAUSED,
    Priority,
    Team,
    Ticket,
    TicketCategory,
    TicketEvent,
    TicketStatus,
)

C = TicketCategory
LABELS = {
    C.payment: "Payment or ledger clarification",
    C.receipt: "Receipt not available",
    C.demand: "Demand discrepancy",
    C.agreement: "Agreement or registration query",
    C.kyc: "KYC or profile correction",
    C.loan: "Loan or bank documentation",
    C.document: "Document download request",
    C.construction: "Construction update enquiry",
    C.modification: "Modification or change request",
    C.parking: "Parking or unit allocation query",
    C.possession: "Possession readiness",
    C.snagging: "Inspection and snagging",
    C.defect: "Defect or warranty complaint",
    C.refund: "Refund or cancellation",
    C.grievance: "General customer grievance",
}
TEAM = {
    C.payment: Team.finance,
    C.receipt: Team.finance,
    C.demand: Team.finance,
    C.refund: Team.finance,
    C.agreement: Team.legal,
    C.kyc: Team.crm,
    C.loan: Team.crm,
    C.document: Team.crm,
    C.construction: Team.projects,
    C.modification: Team.projects,
    C.parking: Team.crm,
    C.possession: Team.projects,
    C.snagging: Team.after_sales,
    C.defect: Team.after_sales,
    C.grievance: Team.crm,
}
TEAM_LABELS = {
    Team.crm: "CRM",
    Team.finance: "Finance",
    Team.legal: "Legal",
    Team.projects: "Projects / site",
    Team.after_sales: "After-sales",
}
# These categories need the customer's confirmation (or a documented non-response) before closing
NEEDS_CONFIRMATION = {C.snagging, C.defect, C.refund, C.grievance, C.modification, C.demand}
RESPONSE_HOURS = {Priority.urgent: 2, Priority.high: 4, Priority.normal: 24, Priority.low: 48}
RESOLUTION_HOURS = {Priority.urgent: 24, Priority.high: 72, Priority.normal: 168, Priority.low: 360}
REOPEN_DAYS = 14


def now() -> datetime:
    return datetime.now(UTC)


def set_targets(t: Ticket, start: datetime, cfg: dict | None = None) -> None:
    """Targets from the settings at the time of raising; the ticket keeps its own window and confirmation rule."""
    cfg = cfg or defaults()
    t.resolution_window_h = int(cfg["resolution_hours"][t.priority.value])
    t.response_due_at = start + timedelta(hours=int(cfg["response_hours"][t.priority.value]))
    t.resolution_due_at = start + timedelta(hours=t.resolution_window_h)
    t.needs_confirmation = bool(cfg["categories"][t.category.value]["needs_confirmation"])


def pause_or_resume(t: Ticket, new: TicketStatus, at: datetime) -> int:
    """Called on every status change. Returns seconds just un-paused (0 if none)."""
    added = 0
    if t.paused_since is not None and t.status in PAUSED and new not in PAUSED:
        added = int((at - t.paused_since).total_seconds())
        if t.status == TicketStatus.waiting_customer:
            t.paused_seconds_customer += added
        else:
            t.paused_seconds_external += added
        t.resolution_due_at += timedelta(seconds=added)
        t.paused_since = None
    elif t.status in PAUSED and new in PAUSED and new != t.status and t.paused_since is not None:
        # switching between the two paused states: close one period, open the next
        added = int((at - t.paused_since).total_seconds())
        if t.status == TicketStatus.waiting_customer:
            t.paused_seconds_customer += added
        else:
            t.paused_seconds_external += added
        t.resolution_due_at += timedelta(seconds=added)
        t.paused_since = at
        added = 0
    if new in PAUSED and t.paused_since is None:
        t.paused_since = at
    return added


def sla(t: Ticket, at: datetime | None = None, at_risk_pct: int = 25) -> dict:
    at = at or now()
    paused_now = int((at - t.paused_since).total_seconds()) if t.paused_since else 0
    due = t.resolution_due_at + timedelta(
        seconds=paused_now
    )  # while paused, the deadline keeps moving
    done_at = t.resolved_at or t.closed_at
    response_breached = (t.acknowledged_at or at) > t.response_due_at
    resolution_breached = (done_at or at) > due
    window = timedelta(hours=t.resolution_window_h or RESOLUTION_HOURS[t.priority]).total_seconds()
    left = (due - at).total_seconds()
    at_risk = (
        not done_at
        and not resolution_breached
        and (
            left < 0.25 * window
            or (not t.acknowledged_at and (t.response_due_at - at).total_seconds() < 3600)
        )
    )
    return {
        "response_due_at": t.response_due_at,
        "resolution_due_at": due,
        "first_response_at": t.acknowledged_at,
        "response_breached": response_breached,
        "resolution_breached": resolution_breached,
        "at_risk": at_risk,
        "paused": t.paused_since is not None,
        "paused_hours_customer": round(
            (
                t.paused_seconds_customer
                + (paused_now if t.status == TicketStatus.waiting_customer else 0)
            )
            / 3600,
            1,
        ),
        "paused_hours_external": round(
            (
                t.paused_seconds_external
                + (paused_now if t.status == TicketStatus.waiting_external else 0)
            )
            / 3600,
            1,
        ),
    }


# ---------------------------------------------------------------- settings (configurable; part 2)
def defaults() -> dict:
    return {
        "response_hours": {p.value: h for p, h in RESPONSE_HOURS.items()},
        "resolution_hours": {p.value: h for p, h in RESOLUTION_HOURS.items()},
        "at_risk_pct": 25,
        "reopen_days": REOPEN_DAYS,
        "categories": {
            c.value: {"team": TEAM[c].value, "needs_confirmation": c in NEEDS_CONFIRMATION}
            for c in TicketCategory
        },
        "escalation": {
            "level2_roles": ["crm_manager"],
            "level3_roles": ["admin", "management"],
            "level3_after_hours": 24,
        },
    }


async def get_settings(db) -> dict:
    from app.models.ticket import ServiceSettings

    row = await db.get(ServiceSettings, 1)
    cfg = defaults()
    if row is not None:
        for k, v in row.data.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


# ---------------------------------------------------------------- escalation engine
async def run_escalations(db, at: datetime, notify_fn) -> dict:
    """Every 15 minutes. Level 1: at risk or first response overdue (owner, or CRM managers if unassigned);
    level 2: resolution breached (configured roles); level 3: breached by more than N hours (configured roles).
    Each level fires once per ticket (reopening starts again); paused or resolution-proposed tickets don't escalate."""
    from sqlalchemy import select

    from app.models.postsales import PostSalesCase
    from app.models.ticket import TicketEscalation
    from app.models.user import Role, User

    cfg = await get_settings(db)
    esc = cfg["escalation"]
    counts = {"level1": 0, "level2": 0, "level3": 0}
    open_ = list(
        await db.scalars(
            select(Ticket).where(
                Ticket.status.notin_([TicketStatus.closed, TicketStatus.resolution_proposed]),
                Ticket.paused_since.is_(None),
            )
        )
    )

    async def people(roles: list[str]) -> list:
        return list(
            await db.scalars(
                select(User).where(
                    User.is_active.is_(True), User.role.in_([Role(r) for r in roles])
                )
            )
        )

    for t in open_:
        s = sla(t, at, cfg["at_risk_pct"])
        due = s["resolution_due_at"]
        response_late = not t.acknowledged_at and at > t.response_due_at
        steps = []
        if t.escalation_level < 1 and (s["at_risk"] or response_late or s["resolution_breached"]):
            owner = await db.get(User, t.owner_id) if t.owner_id else None
            steps.append(
                (
                    1,
                    "First response overdue"
                    if response_late
                    else "At risk of missing the resolution target",
                    [owner] if owner and owner.is_active else await people(["crm_manager"]),
                )
            )
        if t.escalation_level < 2 and s["resolution_breached"]:
            steps.append((2, "Resolution target breached", await people(esc["level2_roles"])))
        if (
            t.escalation_level < 3
            and s["resolution_breached"]
            and (at - due) > timedelta(hours=int(esc["level3_after_hours"]))
        ):
            steps.append(
                (
                    3,
                    f"Breached by more than {esc['level3_after_hours']} hours",
                    await people(esc["level3_roles"]),
                )
            )
        if not steps:
            continue
        case = await db.get(PostSalesCase, t.case_id)
        for level, rule, who in steps:
            names = [u.full_name for u in who]
            t.escalations.append(TicketEscalation(level=level, rule=rule, recipients=names))
            t.events.append(
                TicketEvent(
                    kind="escalated",
                    internal=True,
                    text_=rule,
                    data={"level": level, "recipients": names},
                )
            )
            for u in who:
                notify_fn(
                    db,
                    user_id=u.id,
                    type="ticket_escalated",
                    title=f"Escalation level {level}: TKT-{t.id:05d}, {case.booking.lead.name}",
                    body=rule,
                    link=f"/service/{t.id}",
                )
            t.escalation_level = level
            counts[f"level{level}"] += 1
    return counts


# ---------------------------------------------------------------- reports
def _hours(seconds: float) -> float:
    return round(seconds / 3600, 1)


def report(rows: list[Ticket], at: datetime, at_risk_pct: int = 25) -> dict:
    """Figures for a set of tickets (raised in the period). Times in hours; paused time shown separately."""

    def median(xs: list[float]) -> float | None:
        xs = sorted(xs)
        return (
            None
            if not xs
            else round(
                xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2,
                1,
            )
        )

    def avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 1) if xs else None

    def block(ts: list[Ticket]) -> dict:
        first = [
            _hours((t.acknowledged_at - t.created_at).total_seconds())
            for t in ts
            if t.acknowledged_at
        ]
        resolved = [t for t in ts if t.resolved_at or t.closed_at]
        to_resolve = [
            _hours(
                ((t.resolved_at or t.closed_at) - t.created_at).total_seconds()
                - t.paused_seconds_customer
                - t.paused_seconds_external
            )
            for t in resolved
        ]
        slas = [sla(t, at, at_risk_pct) for t in ts]
        rated = [t.csat for t in ts if t.csat]
        n = len(ts)
        return {
            "raised": n,
            "closed": sum(1 for t in ts if t.status == TicketStatus.closed),
            "open": sum(1 for t in ts if t.status != TicketStatus.closed),
            "first_response_avg_h": avg(first),
            "first_response_median_h": median(first),
            "resolution_avg_h": avg(to_resolve),
            "resolution_median_h": median(to_resolve),
            "paused_customer_h": _hours(sum(t.paused_seconds_customer for t in ts)),
            "paused_external_h": _hours(sum(t.paused_seconds_external for t in ts)),
            "response_breaches": sum(1 for s in slas if s["response_breached"]),
            "resolution_breaches": sum(1 for s in slas if s["resolution_breached"]),
            "at_risk_now": sum(
                1
                for s, t in zip(slas, ts, strict=True)
                if s["at_risk"] and t.status != TicketStatus.closed
            ),
            "escalated": {
                f"level{lv}": sum(1 for t in ts if t.escalation_level >= lv) for lv in (1, 2, 3)
            },
            "reopened": sum(1 for t in ts if t.reopened_count > 0),
            "csat_avg": avg([float(x) for x in rated]),
            "csat_responses": len(rated),
            "csat_distribution": {str(k): rated.count(k) for k in range(1, 6)},
        }

    by_cat = {}
    for c in TicketCategory:
        ts = [t for t in rows if t.category == c]
        if ts:
            by_cat[c.value] = {"label": LABELS[c], **block(ts)}
    by_team = {}
    for tm in Team:
        ts = [t for t in rows if t.team == tm]
        if ts:
            by_team[tm.value] = {"label": TEAM_LABELS[tm], **block(ts)}
    return {"overall": block(rows), "by_category": by_cat, "by_team": by_team}
