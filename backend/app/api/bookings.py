import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

from app.core.deps import DbSession, require_role
from app.models.booking import Booking, BookingStatus
from app.models.user import Role, User
from app.schemas.booking import (
    BookingCancel,
    BookingCreate,
    BookingOut,
    BookingPage,
    BookingQuery,
    BookingTotals,
    BookingUpdate,
)
from app.services import bookings as svc
from app.services import leads as lead_svc
from app.services.audit import log_audit

router = APIRouter(prefix="/bookings", tags=["bookings"])
Viewer = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive, Role.docs))]
Sales = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]


def _http(exc: svc.BookingRuleError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, svc.BookingConflict)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, str(exc))


def _filtered(user: User, q: BookingQuery):
    stmt = svc.visible_bookings(user)
    if q.status:
        stmt = stmt.where(Booking.status == q.status)
    if q.project_id:
        stmt = stmt.where(Booking.project_id == q.project_id)
    if q.sales_exec_id and user.role != Role.executive:
        stmt = stmt.where(Booking.sales_exec_id == q.sales_exec_id)
    if q.date_from:
        stmt = stmt.where(Booking.booking_date >= q.date_from)
    if q.date_to:
        stmt = stmt.where(Booking.booking_date <= q.date_to)
    return stmt


async def _booking(db: DbSession, user: User, booking_id: int) -> Booking:
    b = await db.scalar(svc.visible_bookings(user).where(Booking.id == booking_id))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    return b


@router.get("", response_model=BookingPage)
async def list_bookings(
    q: Annotated[BookingQuery, Query()], user: Viewer, db: DbSession
) -> BookingPage:
    stmt = _filtered(user, q)
    count, agreed, paid, expected, received = await svc.totals(db, stmt)
    rows = await db.scalars(
        stmt.order_by(Booking.booking_date.desc(), Booking.id.desc())
        .offset((q.page - 1) * q.page_size)
        .limit(q.page_size)
    )
    return BookingPage(
        items=[await svc.to_out(db, b) for b in rows],
        total=count,
        page=q.page,
        page_size=q.page_size,
        totals=BookingTotals(
            count=count,
            agreed_value=agreed,
            booking_amount=paid,
            commission_expected=expected,
            commission_received=received,
        ),
        missing_details=await svc.missing_details(db, user)
        if q.status != BookingStatus.cancelled
        else [],
    )


@router.get("/export")
async def export(
    q: Annotated[BookingQuery, Query()], request: Request, user: Manager, db: DbSession
) -> Response:
    rows = [
        [
            "Booking",
            "Status",
            "Booking date",
            "Customer",
            "Mobile",
            "Lead",
            "Project",
            "Building",
            "Floor",
            "Unit",
            "Type",
            "Carpet sq ft",
            "Agreed price",
            "Booking amount",
            "Balance",
            "Payment mode",
            "Reference",
            "Handled by",
            "Channel partner",
            "Commission expected",
            "Commission received",
            "Cancelled",
            "Cancellation reason",
        ]
    ]
    for b in await db.scalars(
        _filtered(user, q.model_copy(update={"page_size": 100})).order_by(
            Booking.booking_date.desc()
        )
    ):
        o = await svc.to_out(db, b)
        rows.append(
            [
                o.booking_code,
                o.status.value,
                o.booking_date,
                o.lead.name,
                o.lead.mobile,
                o.lead.lead_code,
                o.project.name,
                o.unit.building or "",
                "" if o.unit.floor_number is None else o.unit.floor_number,
                o.unit.unit_no,
                o.unit.unit_type.value,
                o.unit.carpet_sqft or "",
                o.agreed_price,
                o.booking_amount,
                o.balance,
                o.payment_mode.value if o.payment_mode else "",
                o.payment_reference or "",
                o.sales_exec.full_name if o.sales_exec else "",
                o.channel_partner or "",
                "" if o.commission_expected is None else o.commission_expected,
                o.commission_received,
                o.cancelled_at.date() if o.cancelled_at else "",
                o.cancellation_reason or "",
            ]
        )
    buf = io.StringIO()
    csv.writer(buf).writerows([[str(c) for c in r] for r in rows])
    log_audit(
        db,
        action="booking.export",
        entity_type="booking",
        actor=user,
        details=q.model_dump(mode="json", exclude_none=True),
        request=request,
    )
    await db.commit()
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="flatons-bookings.csv"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/{booking_id}", response_model=BookingOut)
async def get_booking(booking_id: int, user: Viewer, db: DbSession) -> BookingOut:
    return await svc.to_out(db, await _booking(db, user, booking_id), with_history=True)


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(
    body: BookingCreate, request: Request, user: Sales, db: DbSession
) -> BookingOut:
    lead = await lead_svc.get_visible_lead(db, user, body.lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    if not lead_svc.can_edit(user, lead):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't book for this lead")
    sales_exec = None
    if user.role in lead_svc.MANAGERS:
        exec_id = body.sales_exec_id or lead.assigned_to_id
        if exec_id and exec_id != user.id:
            try:
                sales_exec = await lead_svc.get_assignable_user(db, exec_id)
            except lead_svc.LeadRuleError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    fields = body.model_dump(exclude={"lead_id", "unit_id", "sales_exec_id"})
    try:
        booking = await svc.create(
            db, lead=lead, unit_id=body.unit_id, actor=user, sales_exec=sales_exec, **fields
        )
    except svc.BookingRuleError as exc:
        raise _http(exc) from None
    log_audit(
        db,
        action="booking.create",
        entity_type="booking",
        entity_id=booking.id,
        actor=user,
        details={"lead_id": lead.id, "unit_id": body.unit_id, "agreed_price": body.agreed_price},
        request=request,
    )
    await db.commit()
    await db.refresh(booking)
    return await svc.to_out(db, booking, with_history=True)


@router.patch("/{booking_id}", response_model=BookingOut)
async def update_booking(
    booking_id: int, body: BookingUpdate, request: Request, user: Manager, db: DbSession
) -> BookingOut:
    b = await _booking(db, user, booking_id)
    if b.status != BookingStatus.booked:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Cancelled bookings can't be edited"
        )
    changes = body.model_dump(exclude_unset=True)
    if "booking_date" in changes:
        try:
            svc.check_booking_date(changes["booking_date"])
        except svc.BookingRuleError as exc:
            raise _http(exc) from None
    price = changes.get("agreed_price", b.agreed_price)
    paid = changes.get("booking_amount", b.booking_amount)
    if paid > price:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The booking amount can't be more than the agreed price",
        )
    if changes.get("sales_exec_id"):
        try:
            await lead_svc.get_assignable_user(db, changes["sales_exec_id"])
        except lead_svc.LeadRuleError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if "agreed_price" in changes and "commission_expected" not in changes:
        changes["commission_expected"] = svc.commission_for(price, b.project)
    before = {k: getattr(b, k) for k in changes}
    for k, v in changes.items():
        setattr(b, k, v)
    diff = {k: {"from": str(before[k]), "to": str(v)} for k, v in changes.items() if before[k] != v}
    if diff:
        svc.event(
            db,
            b,
            "commission_received" if set(diff) == {"commission_received"} else "edited",
            user,
            diff,
        )
        log_audit(
            db,
            action="booking.update",
            entity_type="booking",
            entity_id=b.id,
            actor=user,
            details=diff,
            request=request,
        )
    await db.commit()
    return await svc.to_out(db, await _booking(db, user, b.id), with_history=True)


@router.post("/{booking_id}/cancel", response_model=BookingOut)
async def cancel_booking(
    booking_id: int, body: BookingCancel, request: Request, user: Manager, db: DbSession
) -> BookingOut:
    b = await _booking(db, user, booking_id)
    try:
        await svc.cancel(db, b, actor=user, reason=body.reason)
    except svc.BookingRuleError as exc:
        raise _http(exc) from None
    log_audit(
        db,
        action="booking.cancel",
        entity_type="booking",
        entity_id=b.id,
        actor=user,
        details={"reason": body.reason, "unit_id": b.unit_id},
        request=request,
    )
    await db.commit()
    return await svc.to_out(db, await _booking(db, user, b.id), with_history=True)
