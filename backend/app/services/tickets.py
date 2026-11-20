"""Ticket rules: default team per category, confirmation rules, SLA targets and their state.

SLA (part 1: fixed targets by priority; part 2 makes them configurable):
  response target   urgent 2 h, high 4 h, normal 1 working day (24 h), low 2 working days
  resolution target urgent 1 day, high 3 days, normal 7 days, low 15 days
  Paused while waiting for the customer or a third party: the resolution target moves out by the paused time, and the
  paused time is kept (customer / external separately) so reports can show it.
  At risk: less than 25% of the resolution window left (or the response due within an hour, not yet acknowledged).
"""

from datetime import UTC, datetime, timedelta

from app.models.ticket import PAUSED, Priority, Team, Ticket, TicketCategory, TicketStatus

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


def set_targets(t: Ticket, start: datetime) -> None:
    t.response_due_at = start + timedelta(hours=RESPONSE_HOURS[t.priority])
    t.resolution_due_at = start + timedelta(hours=RESOLUTION_HOURS[t.priority])


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


def sla(t: Ticket, at: datetime | None = None) -> dict:
    at = at or now()
    paused_now = int((at - t.paused_since).total_seconds()) if t.paused_since else 0
    due = t.resolution_due_at + timedelta(
        seconds=paused_now
    )  # while paused, the deadline keeps moving
    done_at = t.resolved_at or t.closed_at
    response_breached = (t.acknowledged_at or at) > t.response_due_at
    resolution_breached = (done_at or at) > due
    window = timedelta(hours=RESOLUTION_HOURS[t.priority]).total_seconds()
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
