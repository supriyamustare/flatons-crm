from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import DbSession, require_role
from app.models.booking import Booking, BookingStatus
from app.models.channel_partner import ChannelPartner
from app.models.lead import Lead
from app.models.user import Role, User
from app.schemas.channel_partner import (
    PartnerCustomer,
    PartnerCustomers,
    PartnerIn,
    PartnerOut,
    PartnerQuery,
    PartnerUpdate,
)
from app.schemas.user import UserBrief
from app.services.audit import log_audit
from app.services.leads import visible_leads

router = APIRouter(prefix="/channel-partners", tags=["channel partners"])
Sales = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]


async def _stats(db: DbSession, user: User, ids: list[int]) -> dict[int, tuple[int, int, int]]:
    """Per partner: customers (leads) the user can see, live bookings, booked value."""
    if not ids:
        return {}
    leads = visible_leads(user).where(Lead.channel_partner_id.in_(ids)).subquery()
    lead_counts = dict(
        (
            await db.execute(
                select(leads.c.channel_partner_id, func.count()).group_by(
                    leads.c.channel_partner_id
                )
            )
        ).all()
    )
    b = (
        await db.execute(
            select(
                Booking.channel_partner_id,
                func.count(),
                func.coalesce(func.sum(Booking.agreed_price), 0),
            )
            .join(leads, leads.c.id == Booking.lead_id)
            .where(Booking.status == BookingStatus.booked, Booking.channel_partner_id.in_(ids))
            .group_by(Booking.channel_partner_id)
        )
    ).all()
    books = {r[0]: (r[1], int(r[2])) for r in b}
    return {i: (lead_counts.get(i, 0), *books.get(i, (0, 0))) for i in ids}


def _out(p: ChannelPartner, stats: tuple[int, int, int] | None) -> PartnerOut:
    o = PartnerOut.model_validate(p)
    if stats:
        o.leads, o.bookings, o.booked_value = stats
    return o


async def _get(db: DbSession, partner_id: int) -> ChannelPartner:
    p = await db.get(ChannelPartner, partner_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel partner not found")
    return p


async def _check_unique(
    db: DbSession, mobile: str | None, rera: str | None, exclude: int | None = None
) -> None:
    if mobile and await db.scalar(
        select(ChannelPartner.id).where(
            ChannelPartner.mobile == mobile, ChannelPartner.id != (exclude or 0)
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A channel partner with this mobile number already exists"
        )
    if rera and await db.scalar(
        select(ChannelPartner.id).where(
            func.upper(ChannelPartner.rera_number) == rera.upper(),
            ChannelPartner.id != (exclude or 0),
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A channel partner with this RERA number already exists"
        )


@router.get("", response_model=list[PartnerOut])
async def list_partners(
    q: Annotated[PartnerQuery, Query()], user: Sales, db: DbSession
) -> list[PartnerOut]:
    stmt = select(ChannelPartner)
    if not q.include_inactive:
        stmt = stmt.where(ChannelPartner.is_active.is_(True))
    if q.q:
        like = f"%{q.q.strip()}%"
        stmt = stmt.where(
            or_(
                ChannelPartner.name.ilike(like),
                ChannelPartner.company_name.ilike(like),
                ChannelPartner.rera_number.ilike(like),
            )
        )
    partners = list(
        await db.scalars(
            stmt.order_by(ChannelPartner.name).offset((q.page - 1) * q.page_size).limit(q.page_size)
        )
    )
    stats = await _stats(db, user, [p.id for p in partners])
    return [_out(p, stats.get(p.id)) for p in partners]


@router.post("", response_model=PartnerOut, status_code=status.HTTP_201_CREATED)
async def create_partner(
    body: PartnerIn, request: Request, user: Sales, db: DbSession
) -> PartnerOut:
    rera = body.rera_number.strip().upper() if body.rera_number else None
    await _check_unique(db, body.mobile, rera)
    p = ChannelPartner(
        **body.model_dump(exclude={"rera_number"}), rera_number=rera, created_by_id=user.id
    )
    db.add(p)
    await db.flush()
    log_audit(
        db,
        action="channel_partner.create",
        entity_type="channel_partner",
        entity_id=p.id,
        actor=user,
        details={"name": p.name, "company": p.company_name},
        request=request,
    )
    try:
        await db.commit()
    except IntegrityError:  # two people adding the same partner at the same moment
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This channel partner already exists"
        ) from None
    await db.refresh(p)
    return _out(p, (0, 0, 0))


@router.get("/{partner_id}", response_model=PartnerOut)
async def get_partner(partner_id: int, user: Sales, db: DbSession) -> PartnerOut:
    p = await _get(db, partner_id)
    return _out(p, (await _stats(db, user, [p.id])).get(p.id))


@router.patch("/{partner_id}", response_model=PartnerOut)
async def update_partner(
    partner_id: int, body: PartnerUpdate, request: Request, user: Manager, db: DbSession
) -> PartnerOut:
    p = await _get(db, partner_id)
    changes = body.model_dump(exclude_unset=True)
    for required in ("name", "mobile"):
        if required in changes and not changes[required]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{required.title()} can't be empty"
            )
    if changes.get("rera_number"):
        changes["rera_number"] = changes["rera_number"].strip().upper()
    await _check_unique(db, changes.get("mobile"), changes.get("rera_number"), exclude=p.id)
    if "is_active" in changes:
        p.deactivated_at = None if changes["is_active"] else datetime.now(UTC)
    before = {k: str(getattr(p, k)) for k in changes}
    for k, v in changes.items():
        setattr(p, k, v)
    log_audit(
        db,
        action="channel_partner.update",
        entity_type="channel_partner",
        entity_id=p.id,
        actor=user,
        details={"from": before, "to": {k: str(v) for k, v in changes.items()}},
        request=request,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another channel partner already has this mobile or RERA number",
        ) from None
    await db.refresh(p)
    return _out(p, (await _stats(db, user, [p.id])).get(p.id))


@router.get("/{partner_id}/customers", response_model=PartnerCustomers)
async def partner_customers(
    partner_id: int,
    user: Sales,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PartnerCustomers:
    """Customers this partner brought, newest first, with their booking if any. Executives see their own leads only."""
    await _get(db, partner_id)
    stmt = visible_leads(user).where(Lead.channel_partner_id == partner_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    leads = list(
        await db.scalars(
            stmt.order_by(Lead.created_at.desc(), Lead.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    bookings = (
        {
            b.lead_id: b
            for b in await db.scalars(
                select(Booking).where(
                    Booking.lead_id.in_([lead.id for lead in leads]),
                    Booking.status == BookingStatus.booked,
                )
            )
        }
        if leads
        else {}
    )
    items = []
    for lead in leads:
        b = bookings.get(lead.id)
        items.append(
            PartnerCustomer(
                lead_id=lead.id,
                lead_code=lead.lead_code,
                name=lead.name,
                mobile=lead.mobile,
                status=lead.status,
                project=lead.project.name if lead.project else None,
                owner=UserBrief.model_validate(lead.assigned_to) if lead.assigned_to else None,
                created_at=lead.created_at,
                booking_id=b.id if b else None,
                booking_code=f"BKG-{b.id:05d}" if b else None,
                unit_no=b.unit.unit_no if b else None,
                booked_project=b.project.name if b else None,
                agreed_price=b.agreed_price if b else None,
                booking_date=b.booking_date if b else None,
            )
        )
    return PartnerCustomers(items=items, total=total)
