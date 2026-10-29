"""Booking rules. A booking locks its unit row (SELECT ... FOR UPDATE) so a flat can never be
booked twice, even by two people at the same instant; partial unique indexes back this up."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking, BookingEvent, BookingStatus, PaymentPreference
from app.models.inventory import Building, Floor, UnitStatus
from app.models.lead import Lead, LeadStatus
from app.models.project import Project
from app.models.user import Role, User
from app.schemas.booking import (
    BookingEventOut,
    BookingLead,
    BookingOut,
    BookingUnit,
    CustomerDetails,
    MissingDetails,
)
from app.schemas.channel_partner import PartnerBrief
from app.schemas.project import ProjectBrief
from app.schemas.user import UserBrief
from app.services import inventory as inv
from app.services.leads import IST, MANAGERS, add_activity
from app.services.notifications import notify


class BookingRuleError(ValueError):
    """Broken rule; shown to the user."""


class BookingConflict(BookingRuleError):
    """Someone else got there first (unit taken, lead already booked)."""


def code(b: Booking) -> str:
    return f"BKG-{b.id:05d}"


def visible_bookings(user: User) -> Select:
    """Managers, admins and documents staff see all bookings; executives see the ones they handled."""
    stmt = select(Booking)
    if user.role == Role.executive:
        stmt = stmt.where(Booking.sales_exec_id == user.id)
    return stmt


def commission_for(agreed_price: int, project: Project) -> int | None:
    pct = project.commission_pct
    return round(agreed_price * float(pct) / 100) if pct is not None else None


def event(
    db: AsyncSession, booking: Booking, action: str, actor: User | None, details: dict | None = None
) -> None:
    db.add(
        BookingEvent(
            booking_id=booking.id,
            action=action,
            actor_id=actor.id if actor else None,
            details=details,
        )
    )


async def to_out(db: AsyncSession, b: Booking, with_history: bool = False) -> BookingOut:
    unit = b.unit
    floor = await db.get(Floor, unit.floor_id) if unit.floor_id else None
    building = await db.get(Building, unit.building_id) if unit.building_id else None
    history = []
    if with_history:
        rows = await db.scalars(
            select(BookingEvent)
            .where(BookingEvent.booking_id == b.id)
            .order_by(BookingEvent.at, BookingEvent.id)
        )
        history = [BookingEventOut.model_validate(e) for e in rows]
    return BookingOut(
        id=b.id,
        booking_code=code(b),
        status=b.status,
        lead=BookingLead.model_validate(b.lead),
        project=ProjectBrief.model_validate(b.project),
        unit=BookingUnit(
            id=unit.id,
            unit_no=unit.unit_no,
            unit_type=unit.unit_type,
            building=building.name if building else None,
            floor_number=floor.number if floor else None,
            carpet_sqft=unit.carpet_sqft,
            builtup_sqft=unit.builtup_sqft,
            address_note=unit.address_note,
        ),
        booking_date=b.booking_date,
        agreed_price=b.agreed_price,
        booking_amount=b.booking_amount,
        balance=b.agreed_price - b.booking_amount,
        payment_mode=b.payment_mode,
        payment_reference=b.payment_reference,
        channel_partner=b.channel_partner,
        commission_pct=b.project.commission_pct,
        commission_expected=b.commission_expected,
        commission_received=b.commission_received,
        notes=b.notes,
        sales_exec=UserBrief.model_validate(b.sales_exec) if b.sales_exec else None,
        recorded_by=UserBrief.model_validate(b.recorded_by) if b.recorded_by else None,
        customer=customer_of(b),
        partner=partner_of(b),
        created_at=b.created_at,
        cancelled_at=b.cancelled_at,
        cancellation_reason=b.cancellation_reason,
        history=history,
    )


CUSTOMER_FIELDS = (
    "customer_name",
    "applicant_name",
    "customer_mobile",
    "customer_email",
    "customer_address",
    "payment_preference",
    "bank_name",
    "banker_name",
    "banker_phone",
)


def partner_of(b: Booking) -> PartnerBrief | None:
    """The channel partner who brought this booking's customer, if any."""
    p = b.lead.channel_partner if b.channel_partner_id else None
    return PartnerBrief.model_validate(p) if p else None


def customer_of(b: Booking) -> CustomerDetails:
    """The booking's customer details, falling back to the lead for name, mobile and email."""
    d = {k: getattr(b, k) for k in CUSTOMER_FIELDS}
    d["customer_name"] = d["customer_name"] or b.lead.name
    d["customer_mobile"] = d["customer_mobile"] or b.lead.mobile
    d["customer_email"] = d["customer_email"] or b.lead.email
    return CustomerDetails.model_construct(**d)


def apply_customer(b: Booking, details: dict) -> dict:
    """Set customer fields; bank fields are cleared unless paying by bank loan. Returns what changed."""
    changed = {}
    for k in CUSTOMER_FIELDS:
        if k in details:
            v = details[k].strip() if isinstance(details[k], str) else details[k]
            v = v or None
            if getattr(b, k) != v:
                changed[k] = {"from": str(getattr(b, k)), "to": str(v)}
                setattr(b, k, v)
    if b.payment_preference != PaymentPreference.bank_loan:
        b.bank_name = b.banker_name = b.banker_phone = None
    return changed


def check_booking_date(d: date) -> None:
    today = datetime.now(UTC).astimezone(IST).date()
    if d > today:
        raise BookingRuleError("The booking date can't be in the future")
    if d < today - timedelta(days=730):
        raise BookingRuleError("The booking date is more than two years ago")


async def create(
    db: AsyncSession,
    *,
    lead: Lead,
    unit_id: int,
    actor: User,
    sales_exec: User | None,
    customer: dict | None = None,
    **fields,
) -> Booking:
    """Caller has checked the user may book this lead. Caller commits."""
    if lead.status in (LeadStatus.lost, LeadStatus.junk):
        raise BookingRuleError("This lead is marked Lost or Junk; reopen it before booking")
    if await db.scalar(
        select(Booking.id).where(Booking.lead_id == lead.id, Booking.status == BookingStatus.booked)
    ):
        raise BookingConflict(
            f"{lead.name} already has a booking; cancel it first to book another flat"
        )
    check_booking_date(fields["booking_date"])

    now = datetime.now(UTC)
    unit = await inv.lock_unit(
        db, unit_id
    )  # waits here if someone else is booking this flat right now
    if unit is None:
        raise BookingRuleError("That unit doesn't exist")
    project = await db.get(Project, unit.project_id)
    if (
        unit.status == UnitStatus.on_hold
        and not inv.hold_is_expired(unit, now)
        and unit.held_for_lead_id not in (None, lead.id)
    ):
        raise BookingConflict(f"Unit {unit.unit_no} is on hold for another customer")
    if unit.status not in (UnitStatus.available, UnitStatus.on_hold):
        raise BookingConflict(
            f"Unit {unit.unit_no} is {unit.status.value.replace('_', ' ')} and can't be booked"
        )

    booking = Booking(
        lead_id=lead.id,
        unit_id=unit.id,
        project_id=unit.project_id,
        status=BookingStatus.booked,
        commission_expected=commission_for(fields["agreed_price"], project),
        sales_exec_id=(sales_exec or actor).id,
        recorded_by_id=actor.id,
        **fields,
    )
    booking.channel_partner_id = lead.channel_partner_id
    apply_customer(
        booking,
        {
            "customer_name": lead.name,
            "customer_mobile": lead.mobile,
            "customer_email": lead.email,
            **(customer or {}),
        },
    )
    db.add(booking)
    await db.flush()

    unit.status = UnitStatus.booked
    inv._clear_hold(unit)
    unit.booking_id = booking.id
    lead.status = LeadStatus.booked  # the model listener stamps status_changed_at
    lead.lost_reason = None
    lead.project_id = unit.project_id
    if lead.assigned_to_id is None:
        lead.assigned_to_id = booking.sales_exec_id
    price = f"₹{booking.agreed_price:,}"
    add_activity(
        db,
        lead,
        actor=actor,
        type="booked",
        details={
            "booking_id": booking.id,
            "booking_code": code(booking),
            "project": project.name,
            "unit_no": unit.unit_no,
            "agreed_price": booking.agreed_price,
        },
    )
    event(
        db,
        booking,
        "created",
        actor,
        {
            "unit_no": unit.unit_no,
            "agreed_price": booking.agreed_price,
            "booking_amount": booking.booking_amount,
        },
    )
    managers = await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role.in_(list(MANAGERS)), User.id != actor.id
        )
    )
    who = sales_exec.full_name if sales_exec and sales_exec.id != actor.id else actor.full_name
    for uid in managers:
        notify(
            db,
            user_id=uid,
            type="booking",
            title=f"Booked: {lead.name}",
            body=f"{who} booked unit {unit.unit_no}, {project.name}, at {price}",
            link=f"/bookings/{booking.id}",
        )
    return booking


async def cancel(db: AsyncSession, booking: Booking, *, actor: User, reason: str) -> None:
    if booking.status != BookingStatus.booked:
        raise BookingRuleError("This booking is already cancelled")
    unit = await inv.lock_unit(db, booking.unit_id)
    booking.status = BookingStatus.cancelled
    booking.cancelled_at = datetime.now(UTC)
    booking.cancelled_by_id = actor.id
    booking.cancellation_reason = reason
    if unit is not None and unit.booking_id == booking.id:
        unit.status = UnitStatus.available
        unit.booking_id = None
    lead = booking.lead
    if lead.status == LeadStatus.booked:
        lead.status = LeadStatus.negotiation
    add_activity(
        db,
        lead,
        actor=actor,
        type="booking_cancelled",
        note=reason,
        details={
            "booking_id": booking.id,
            "booking_code": code(booking),
            "unit_no": booking.unit.unit_no,
        },
    )
    event(db, booking, "cancelled", actor, {"reason": reason})
    if booking.sales_exec_id and booking.sales_exec_id != actor.id:
        notify(
            db,
            user_id=booking.sales_exec_id,
            type="booking_cancelled",
            title=f"Booking cancelled: {lead.name}",
            body=f"Unit {booking.unit.unit_no} is available again. Reason: {reason}",
            link=f"/bookings/{booking.id}",
        )


async def missing_details(db: AsyncSession, user: User) -> list[MissingDetails]:
    """Booked leads with no live booking record (marked Booked by status before bookings existed)."""
    stmt = (
        select(Lead)
        .where(
            Lead.deleted_at.is_(None),
            Lead.status == LeadStatus.booked,
            ~select(Booking.id)
            .where(Booking.lead_id == Lead.id, Booking.status == BookingStatus.booked)
            .exists(),
        )
        .order_by(Lead.status_changed_at.desc())
    )
    if user.role == Role.executive:
        stmt = stmt.where(Lead.assigned_to_id == user.id)
    return [
        MissingDetails(
            lead_id=lead.id,
            lead_code=lead.lead_code,
            name=lead.name,
            mobile=lead.mobile,
            project=ProjectBrief.model_validate(lead.project) if lead.project else None,
            assigned_to=UserBrief.model_validate(lead.assigned_to) if lead.assigned_to else None,
            booked_since=lead.status_changed_at,
        )
        for lead in await db.scalars(stmt.limit(200))
    ]


async def totals(db: AsyncSession, stmt: Select) -> tuple[int, int, int, int, int]:
    sub = stmt.subquery()
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(sub.c.agreed_price), 0),
                func.coalesce(func.sum(sub.c.booking_amount), 0),
                func.coalesce(func.sum(sub.c.commission_expected), 0),
                func.coalesce(func.sum(sub.c.commission_received), 0),
            )
        )
    ).one()
    return tuple(int(x) for x in row)
