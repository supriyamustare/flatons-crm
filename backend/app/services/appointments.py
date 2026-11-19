"""The common calendar: appointments plus registration appointments (from agreements) and sales site visits,
the double-booking check, and the daily appointment reminders."""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agreement import Agreement, AgreementStatus
from app.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from app.models.postsales import PostSalesCase
from app.models.user import POSTSALES_ROLES, Role, User
from app.models.visit import SiteVisit, VisitStatus

IST = timezone(timedelta(hours=5, minutes=30))
LABELS = {
    AppointmentKind.agreement_signing: "Agreement signing",
    AppointmentKind.registration: "Registration",
    AppointmentKind.site_visit: "Site visit",
    AppointmentKind.inspection: "Customer inspection",
    AppointmentKind.possession: "Possession handover",
    AppointmentKind.defect_inspection: "Defect inspection",
    AppointmentKind.document_collection: "Document collection",
    AppointmentKind.other: "Other",
}
LIVE = (AppointmentStatus.scheduled,)
SALES_VIEW = (Role.admin, Role.manager, Role.executive)


def day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=IST)
    return start, start + timedelta(days=1)


async def clashes(
    db: AsyncSession,
    owner_id: int | None,
    starts_at: datetime,
    minutes: int,
    exclude_id: int | None = None,
) -> list[Appointment]:
    if owner_id is None:
        return []
    end = starts_at + timedelta(minutes=minutes)
    rows = await db.scalars(
        select(Appointment).where(
            Appointment.owner_id == owner_id,
            Appointment.status.in_(LIVE),
            Appointment.starts_at < end,
            Appointment.starts_at > starts_at - timedelta(hours=8),
        )
    )
    return [
        a
        for a in rows
        if a.id != exclude_id and a.starts_at + timedelta(minutes=a.duration_min) > starts_at
    ]


async def calendar(db: AsyncSession, user: User, start: date, days: int, mine: bool) -> list[dict]:
    lo, _ = day_bounds(start)
    hi = lo + timedelta(days=days)
    items: list[dict] = []
    if user.role in POSTSALES_ROLES:
        q = select(Appointment).where(
            Appointment.starts_at >= lo,
            Appointment.starts_at < hi,
            Appointment.status.notin_([AppointmentStatus.rescheduled]),
        )
        if mine:
            q = q.where(Appointment.owner_id == user.id)
        owners = {}
        for a in await db.scalars(q.order_by(Appointment.starts_at)):
            case = await db.get(PostSalesCase, a.case_id)
            if a.owner_id and a.owner_id not in owners:
                owners[a.owner_id] = await db.get(User, a.owner_id)
            items.append(
                {
                    "id": f"apt-{a.id}",
                    "source": "appointment",
                    "kind": a.kind.value,
                    "label": LABELS[a.kind],
                    "title": a.title or LABELS[a.kind],
                    "customer": case.booking.lead.name,
                    "case_code": f"PSC-{case.id:05d}",
                    "starts_at": a.starts_at,
                    "duration_min": a.duration_min,
                    "location": a.location,
                    "status": a.status.value,
                    "confirmed": bool(a.confirmed_on),
                    "owner": owners[a.owner_id].full_name
                    if a.owner_id in owners and owners[a.owner_id]
                    else None,
                    "link": f"/post-sales/{case.id}?tab=appointments",
                }
            )
        # Registration appointments recorded in agreements (not entered twice)
        q = select(Agreement).where(
            Agreement.appointment_at >= lo,
            Agreement.appointment_at < hi,
            Agreement.status.in_([AgreementStatus.execution_prep, AgreementStatus.registered]),
        )
        for ag in await db.scalars(q):
            case = await db.get(PostSalesCase, ag.case_id)
            if mine and case.owner_id != user.id:
                continue
            items.append(
                {
                    "id": f"agr-{ag.id}",
                    "source": "agreement",
                    "kind": "registration",
                    "label": "Registration",
                    "title": f"Registration (AGR-{ag.id:05d})",
                    "customer": case.booking.lead.name,
                    "case_code": f"PSC-{case.id:05d}",
                    "starts_at": ag.appointment_at,
                    "duration_min": 120,
                    "location": ag.sro_office,
                    "status": "attended"
                    if ag.status == AgreementStatus.registered
                    else "scheduled",
                    "confirmed": True,
                    "owner": None,
                    "link": f"/post-sales/{case.id}?tab=agreement",
                }
            )
    if user.role in SALES_VIEW:
        q = select(SiteVisit).where(
            SiteVisit.scheduled_at >= lo,
            SiteVisit.scheduled_at < hi,
            SiteVisit.status != VisitStatus.cancelled,
        )
        if mine or user.role == Role.executive:
            q = q.where(SiteVisit.host_id == user.id)
        for v in await db.scalars(q):
            items.append(
                {
                    "id": f"vis-{v.id}",
                    "source": "sales_visit",
                    "kind": "site_visit",
                    "label": "Site visit (sales)",
                    "title": f"Site visit: {v.project.name}",
                    "customer": v.lead.name,
                    "case_code": None,
                    "starts_at": v.scheduled_at,
                    "duration_min": 60,
                    "location": v.project.name,
                    "status": {"completed": "attended"}.get(v.status.value, v.status.value),
                    "confirmed": False,
                    "owner": None,
                    "link": f"/leads/{v.lead_id}",
                }
            )
    return sorted(items, key=lambda x: x["starts_at"])


async def run_appointment_reminders(db: AsyncSession, today: date, send) -> dict:
    """Owner reminders: tomorrow's and today's appointments; attendance not recorded; missed-appointment follow-ups."""
    counts = {
        "appointments_tomorrow": 0,
        "appointments_today": 0,
        "attendance_missing": 0,
        "missed_follow_ups": 0,
    }
    crm = list(
        await db.scalars(
            select(User.id).where(User.is_active.is_(True), User.role == Role.crm_manager)
        )
    )
    lo, _ = day_bounds(today - timedelta(days=3))
    _, hi = day_bounds(today + timedelta(days=1))
    rows = list(
        await db.scalars(
            select(Appointment).where(
                Appointment.status == AppointmentStatus.scheduled,
                Appointment.starts_at >= lo,
                Appointment.starts_at < hi,
            )
        )
    )
    rows += list(
        await db.scalars(
            select(Appointment).where(
                Appointment.status == AppointmentStatus.no_show, Appointment.follow_up_on == today
            )
        )
    )
    for a in rows:
        case = await db.get(PostSalesCase, a.case_id)
        who = [a.owner_id] if a.owner_id else crm
        sent = dict(a.reminders_sent or {})
        when = a.starts_at.astimezone(IST)
        name, link, label = (
            case.booking.lead.name,
            f"/post-sales/{case.id}?tab=appointments",
            LABELS[a.kind],
        )
        if a.status == AppointmentStatus.no_show:
            if sent.get("missed") != today.isoformat():
                counts["missed_follow_ups"] += await send(
                    who,
                    type="appointment_missed_follow_up",
                    title=f"Follow up the missed {label.lower()}: {name}",
                    body=f"Missed on {when:%d %b, %I:%M %p}. Contact the customer and reschedule.",
                    link=link,
                )
                sent["missed"] = today.isoformat()
        elif when.date() == today + timedelta(days=1) and sent.get("tomorrow") != today.isoformat():
            counts["appointments_tomorrow"] += await send(
                who,
                type="appointment_tomorrow",
                title=f"Tomorrow {when:%I:%M %p}: {label}, {name}",
                body=(a.location or "")
                + (f". Bring: {a.required_docs}" if a.required_docs else ""),
                link=link,
            )
            sent["tomorrow"] = today.isoformat()
        elif when.date() == today and sent.get("today") != today.isoformat():
            counts["appointments_today"] += await send(
                who,
                type="appointment_today",
                title=f"Today {when:%I:%M %p}: {label}, {name}",
                body=(a.location or "")
                + ("" if a.confirmed_on else ". Not yet confirmed by the customer"),
                link=link,
            )
            sent["today"] = today.isoformat()
        elif when.date() < today and sent.get("attendance") is None:
            counts["attendance_missing"] += await send(
                who,
                type="appointment_attendance_missing",
                title=f"Record attendance: {label}, {name}",
                body=f"The appointment on {when:%d %b} has no attendance recorded",
                link=link,
            )
            sent["attendance"] = today.isoformat()
        a.reminders_sent = sent
    return counts
