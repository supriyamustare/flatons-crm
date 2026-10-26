"""Inventory rules: holds and releases (row-locked), bulk generation, and the inventory tree."""

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Building, Floor, Unit, UnitStatus
from app.models.lead import Lead
from app.models.project import Project
from app.models.user import User
from app.schemas.inventory import (
    BuildingTree,
    FloorOut,
    GenerateUnits,
    HeldLead,
    Inventory,
    UnitOut,
)
from app.schemas.project import ProjectOut, UnitCounts
from app.services.audit import log_audit
from app.services.leads import add_activity

DEFAULT_HOLD = timedelta(hours=48)
MAX_HOLD = timedelta(days=14)


class InventoryRuleError(ValueError):
    """A business rule was broken; the message is shown to the user."""


class UnitConflict(InventoryRuleError):
    """The unit is not in a state that allows this (e.g. someone else just held it)."""


async def lock_unit(db: AsyncSession, unit_id: int) -> Unit | None:
    """Load a unit with a row lock (SELECT ... FOR UPDATE). Anyone else trying to change the
    same unit waits until this transaction ends, then sees the new state: no double holds or
    double bookings."""
    return await db.scalar(
        select(Unit)
        .where(Unit.id == unit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def hold_is_expired(unit: Unit, now: datetime) -> bool:
    return (
        unit.status == UnitStatus.on_hold
        and unit.hold_expires_at is not None
        and unit.hold_expires_at <= now
    )


def _clear_hold(unit: Unit) -> None:
    unit.held_by_id = None
    unit.held_for_lead_id = None
    unit.held_at = None
    unit.hold_expires_at = None
    unit.hold_note = None


async def hold_unit(
    db: AsyncSession,
    unit: Unit,
    *,
    actor: User,
    expires_at: datetime,
    lead: Lead | None,
    note: str | None,
    request: Request | None = None,
    now: datetime | None = None,
) -> None:
    """Caller must have loaded `unit` with lock_unit()."""
    now = now or datetime.now(UTC)
    if unit.status == UnitStatus.on_hold and not hold_is_expired(unit, now):
        holder = unit.held_by.full_name if unit.held_by else "someone"
        raise UnitConflict(f"Unit {unit.unit_no} is already on hold by {holder}")
    if unit.status not in (UnitStatus.available, UnitStatus.on_hold):
        raise UnitConflict(
            f"Unit {unit.unit_no} is {unit.status.value.replace('_', ' ')} and can't be held"
        )
    if expires_at <= now:
        raise InventoryRuleError("The hold must end in the future")
    if expires_at > now + MAX_HOLD:
        raise InventoryRuleError("Holds can last at most 14 days")

    unit.status = UnitStatus.on_hold
    unit.held_by_id = actor.id
    unit.held_for_lead_id = lead.id if lead else None
    unit.held_at = now
    unit.hold_expires_at = expires_at
    unit.hold_note = note
    details = {"unit_id": unit.id, "unit_no": unit.unit_no, "expires_at": expires_at.isoformat()}
    if lead:
        details["lead_id"] = lead.id
        add_activity(db, lead, actor=actor, type="unit_held", note=note, details=details)
    log_audit(
        db,
        action="unit.hold",
        entity_type="unit",
        entity_id=unit.id,
        actor=actor,
        details=details,
        request=request,
    )


async def release_unit(
    db: AsyncSession, unit: Unit, *, actor: User | None, reason: str, request: Request | None = None
) -> None:
    """Caller must have loaded `unit` with lock_unit()."""
    if unit.status != UnitStatus.on_hold:
        raise UnitConflict(f"Unit {unit.unit_no} isn't on hold")
    details = {"unit_no": unit.unit_no, "reason": reason, "held_by_id": unit.held_by_id}
    lead = await db.get(Lead, unit.held_for_lead_id) if unit.held_for_lead_id else None
    unit.status = UnitStatus.available
    _clear_hold(unit)
    if lead is not None and lead.deleted_at is None:
        add_activity(
            db,
            lead,
            actor=actor,
            type="unit_released",
            details={"unit_id": unit.id, "unit_no": unit.unit_no, "reason": reason},
        )
    log_audit(
        db,
        action="unit.release",
        entity_type="unit",
        entity_id=unit.id,
        actor=actor,
        details=details,
        request=request,
    )


async def release_expired_holds(db: AsyncSession, now: datetime | None = None) -> int:
    """Release every hold whose time is up. SKIP LOCKED: units being changed right now are left
    for the next run instead of blocking. Returns how many were released."""
    now = now or datetime.now(UTC)
    units = list(
        await db.scalars(
            select(Unit)
            .where(Unit.status == UnitStatus.on_hold, Unit.hold_expires_at <= now)
            .with_for_update(skip_locked=True)
        )
    )
    for unit in units:
        await release_unit(db, unit, actor=None, reason="expired")
    return len(units)


async def generate_units(db: AsyncSession, building: Building, spec: GenerateUnits) -> int:
    """Create floors (if missing) and units numbered floor + position: 101, 102 ... 1206.
    Ground floor is G01, G02; basements B1-01. Refuses if any unit number already exists."""
    floors = {
        f.number: f for f in await db.scalars(select(Floor).where(Floor.building_id == building.id))
    }
    existing = set(await db.scalars(select(Unit.unit_no).where(Unit.building_id == building.id)))

    def number(floor: int, pos: int) -> str:
        if floor == 0:
            return f"G{pos:02d}"
        if floor < 0:
            return f"B{-floor}-{pos:02d}"
        return f"{floor}{pos:02d}"

    planned = [
        (fl, number(fl, pos))
        for fl in range(spec.floor_from, spec.floor_to + 1)
        for pos in range(1, spec.units_per_floor + 1)
    ]
    clash = sorted({no for _, no in planned} & existing)
    if clash:
        shown = ", ".join(clash[:5]) + ("…" if len(clash) > 5 else "")
        raise UnitConflict(f"These unit numbers already exist in {building.name}: {shown}")

    for fl in range(spec.floor_from, spec.floor_to + 1):
        if fl not in floors:
            floors[fl] = Floor(building_id=building.id, number=fl)
            db.add(floors[fl])
    await db.flush()
    for fl, no in planned:
        db.add(
            Unit(
                project_id=building.project_id,
                building_id=building.id,
                floor_id=floors[fl].id,
                unit_no=no,
                unit_type=spec.unit_type,
                carpet_sqft=spec.carpet_sqft,
                builtup_sqft=spec.builtup_sqft,
                base_price=spec.base_price,
                current_asking_price=spec.base_price,
            )
        )
    return len(planned)


def _count(units: list[Unit]) -> UnitCounts:
    c = UnitCounts(total=len(units))
    for u in units:
        setattr(c, u.status.value, getattr(c, u.status.value) + 1)
    return c


async def project_unit_counts(db: AsyncSession, project_ids: list[int]) -> dict[int, UnitCounts]:
    rows = await db.execute(
        select(Unit.project_id, Unit.status, func.count())
        .where(Unit.project_id.in_(project_ids))
        .group_by(Unit.project_id, Unit.status)
    )
    out: dict[int, UnitCounts] = defaultdict(UnitCounts)
    for pid, status, n in rows:
        c = out[pid]
        setattr(c, status.value, n)
        c.total += n
    return out


async def unit_out(
    db: AsyncSession,
    unit: Unit,
    now: datetime,
    floor_number: int | None = None,
    leads: dict[int, Lead] | None = None,
) -> UnitOut:
    out = UnitOut.model_validate(unit)
    out.floor_number = floor_number
    out.hold_expired = hold_is_expired(unit, now)
    if unit.held_for_lead_id:
        lead = (leads or {}).get(unit.held_for_lead_id) or await db.get(Lead, unit.held_for_lead_id)
        if lead is not None:
            out.held_for = HeldLead(id=lead.id, name=lead.name, lead_code=lead.lead_code)
    return out


async def build_inventory(
    db: AsyncSession, project: Project, now: datetime | None = None
) -> Inventory:
    now = now or datetime.now(UTC)
    buildings = list(
        await db.scalars(
            select(Building)
            .where(Building.project_id == project.id)
            .order_by(Building.sort_order, Building.name)
        )
    )
    floors = (
        list(
            await db.scalars(
                select(Floor)
                .where(Floor.building_id.in_([b.id for b in buildings]))
                .order_by(Floor.number.desc())
            )
        )
        if buildings
        else []
    )
    units = list(
        await db.scalars(select(Unit).where(Unit.project_id == project.id).order_by(Unit.unit_no))
    )
    lead_ids = {u.held_for_lead_id for u in units if u.held_for_lead_id}
    leads = (
        {lead.id: lead for lead in await db.scalars(select(Lead).where(Lead.id.in_(lead_ids)))}
        if lead_ids
        else {}
    )

    by_floor: dict[int, list[Unit]] = defaultdict(list)
    listings: list[Unit] = []
    for u in units:
        (by_floor[u.floor_id] if u.floor_id else listings).append(u)

    trees = []
    for b in buildings:
        b_floors = [f for f in floors if f.building_id == b.id]
        b_units = [u for f in b_floors for u in by_floor[f.id]]
        trees.append(
            BuildingTree(
                id=b.id,
                name=b.name,
                sort_order=b.sort_order,
                counts=_count(b_units),
                floors=[
                    FloorOut(
                        id=f.id,
                        number=f.number,
                        units=[
                            await unit_out(db, u, now, f.number, leads)
                            for u in sorted(by_floor[f.id], key=_natural)
                        ],
                    )
                    for f in b_floors
                ],
            )
        )
    return Inventory(
        project=ProjectOut.model_validate(project),
        counts=_count(units),
        buildings=trees,
        listings=[await unit_out(db, u, now, None, leads) for u in sorted(listings, key=_natural)],
    )


def _natural(u: Unit) -> tuple:
    """Sort 101, 102, 110 rather than 101, 110, 102."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", u.unit_no))
