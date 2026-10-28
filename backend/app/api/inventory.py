from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession, require_role
from app.models.inventory import Building, Floor, Unit, UnitStatus
from app.models.project import Project, ProjectType
from app.models.user import Role, User
from app.schemas.inventory import (
    BuildingOut,
    BuildingUpdate,
    FloorCreate,
    GenerateUnits,
    HoldRequest,
    UnitCreate,
    UnitOut,
    UnitUpdate,
)
from app.services import inventory as inv
from app.services import leads as lead_svc
from app.services.audit import log_audit

router = APIRouter(tags=["inventory"])
Admin = Annotated[User, Depends(require_role(Role.admin))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]

# Units in these states are part of a sale in progress and can't be deleted.
IN_USE = {UnitStatus.on_hold, UnitStatus.booked, UnitStatus.sold}


def _http(exc: inv.InventoryRuleError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, inv.UnitConflict)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, str(exc))


async def _building(db: DbSession, building_id: int) -> Building:
    b = await db.get(Building, building_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Building not found")
    return b


async def _locked_unit(db: DbSession, unit_id: int) -> Unit:
    unit = await inv.lock_unit(db, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")
    return unit


async def _unit_response(db: DbSession, unit: Unit) -> UnitOut:
    await db.refresh(unit)
    floor = await db.get(Floor, unit.floor_id) if unit.floor_id else None
    return await inv.unit_out(db, unit, datetime.now(UTC), floor.number if floor else None)


# ---- Buildings and floors (admin) -----------------------------------------


@router.patch("/buildings/{building_id}", response_model=BuildingOut)
async def update_building(
    building_id: int, body: BuildingUpdate, request: Request, admin: Admin, db: DbSession
) -> Building:
    b = await _building(db, building_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    log_audit(
        db,
        action="building.update",
        entity_type="building",
        entity_id=b.id,
        actor=admin,
        details=body.model_dump(exclude_unset=True),
        request=request,
    )
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Another building in this project has that name"
        ) from None
    await db.refresh(b)
    return b


@router.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_building(building_id: int, request: Request, admin: Admin, db: DbSession) -> None:
    b = await _building(db, building_id)
    busy = await db.scalar(
        select(Unit.unit_no).where(Unit.building_id == b.id, Unit.status.in_(IN_USE))
    )
    if busy:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Unit {busy} is on hold, booked or sold, so {b.name} can't be deleted",
        )
    log_audit(
        db,
        action="building.delete",
        entity_type="building",
        entity_id=b.id,
        actor=admin,
        details={"name": b.name, "project_id": b.project_id},
        request=request,
    )
    await db.delete(b)
    await db.commit()


@router.post("/buildings/{building_id}/floors", status_code=status.HTTP_201_CREATED)
async def add_floor(building_id: int, body: FloorCreate, admin: Admin, db: DbSession) -> dict:
    b = await _building(db, building_id)
    if await db.scalar(
        select(Floor.id).where(Floor.building_id == b.id, Floor.number == body.number)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{b.name} already has floor {body.number}")
    floor = Floor(building_id=b.id, number=body.number)
    db.add(floor)
    await db.commit()
    return {"id": floor.id, "number": floor.number}


@router.post("/buildings/{building_id}/generate", status_code=status.HTTP_201_CREATED)
async def generate(
    building_id: int, body: GenerateUnits, request: Request, admin: Admin, db: DbSession
) -> dict:
    """Bulk-create floors and units, e.g. floors 1-4 x 6 units -> 101..106 ... 401..406."""
    b = await _building(db, building_id)
    try:
        created = await inv.generate_units(db, b, body)
    except inv.InventoryRuleError as exc:
        raise _http(exc) from None
    log_audit(
        db,
        action="units.generate",
        entity_type="building",
        entity_id=b.id,
        actor=admin,
        details={
            "created": created,
            "floors": [body.floor_from, body.floor_to],
            "per_floor": body.units_per_floor,
        },
        request=request,
    )
    await db.commit()
    return {"created": created}


@router.delete("/floors/{floor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_floor(floor_id: int, admin: Admin, db: DbSession) -> None:
    floor = await db.get(Floor, floor_id)
    if floor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Floor not found")
    if await db.scalar(select(Unit.id).where(Unit.floor_id == floor.id, Unit.status.in_(IN_USE))):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A unit on this floor is on hold, booked or sold"
        )
    await db.delete(floor)
    await db.commit()


# ---- Units ----------------------------------------------------------------


@router.post(
    "/projects/{project_id}/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED
)
async def create_unit(
    project_id: int, body: UnitCreate, request: Request, admin: Admin, db: DbSession
) -> UnitOut:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    floor = await db.get(Floor, body.floor_id) if body.floor_id else None
    if project.project_type == ProjectType.developer:
        if floor is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose the floor this unit is on"
            )
        building = await db.get(Building, floor.building_id)
        if building is None or building.project_id != project.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "That floor isn't in this project"
            )
    elif body.floor_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Resale listings don't use floors"
        )
    unit = Unit(
        project_id=project.id,
        floor_id=floor.id if floor else None,
        building_id=floor.building_id if floor else None,
        **body.model_dump(exclude={"floor_id"}),
    )
    db.add(unit)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Unit {body.unit_no} already exists here"
        ) from None
    log_audit(
        db,
        action="unit.create",
        entity_type="unit",
        entity_id=unit.id,
        actor=admin,
        details={"project_id": project.id, "unit_no": unit.unit_no},
        request=request,
    )
    await db.commit()
    return await _unit_response(db, unit)


@router.get("/units/{unit_id}", response_model=UnitOut)
async def get_unit(unit_id: int, _: CurrentUser, db: DbSession) -> UnitOut:
    unit = await db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")
    return await _unit_response(db, unit)


PRICE_AND_AREA = {"carpet_sqft", "builtup_sqft", "rate_psf", "base_price", "current_asking_price"}


@router.patch("/units/{unit_id}", response_model=UnitOut)
async def update_unit(
    unit_id: int, body: UnitUpdate, request: Request, admin: Manager, db: DbSession
) -> UnitOut:
    """Admins change anything; managers change price and area."""
    unit = await _locked_unit(db, unit_id)
    changes = body.model_dump(exclude_unset=True)
    if admin.role != Role.admin and set(changes) - PRICE_AND_AREA:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Managers can change price and area only")
    new_status = changes.pop("status", None)
    if new_status is not None and new_status != unit.status:
        if unit.status in (UnitStatus.on_hold, UnitStatus.booked):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Release the {unit.status.value.replace('_', ' ')} first"
            )
        changes["status"] = new_status
    carpet = changes.get("carpet_sqft", unit.carpet_sqft)
    builtup = changes.get("builtup_sqft", unit.builtup_sqft)
    if carpet and builtup and builtup < carpet:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Built-up area can't be smaller than carpet area"
        )
    # A rate per sq ft sets the asking price: rate x saleable area (built-up, else carpet)
    rate = changes.get("rate_psf", unit.rate_psf)
    if (
        rate
        and "current_asking_price" not in changes
        and ({"rate_psf", "carpet_sqft", "builtup_sqft"} & set(changes))
    ):
        area = builtup or carpet
        if area:
            changes["current_asking_price"] = int(round(float(rate) * float(area)))
    before = {k: str(getattr(unit, k)) for k in changes}
    for k, v in changes.items():
        setattr(unit, k, v)
    log_audit(
        db,
        action="unit.update",
        entity_type="unit",
        entity_id=unit.id,
        actor=admin,
        details={"from": before, "to": {k: str(v) for k, v in changes.items()}},
        request=request,
    )
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Another unit already has that number"
        ) from None
    return await _unit_response(db, unit)


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(unit_id: int, request: Request, admin: Admin, db: DbSession) -> None:
    unit = await _locked_unit(db, unit_id)
    if unit.status in IN_USE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Unit {unit.unit_no} is {unit.status.value.replace('_', ' ')}; withdraw it instead",
        )
    log_audit(
        db,
        action="unit.delete",
        entity_type="unit",
        entity_id=unit.id,
        actor=admin,
        details={"unit_no": unit.unit_no, "project_id": unit.project_id},
        request=request,
    )
    await db.delete(unit)
    await db.commit()


@router.patch("/units/{unit_id}/hold", response_model=UnitOut)
async def hold(
    unit_id: int, body: HoldRequest, request: Request, user: Manager, db: DbSession
) -> UnitOut:
    """Put a unit on hold (admins and managers). Row-locked, so two people can't hold it at once."""
    now = datetime.now(UTC)
    lead = None
    if body.lead_id is not None:
        lead = await lead_svc.get_visible_lead(db, user, body.lead_id)
        if lead is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That lead doesn't exist")
    unit = await _locked_unit(db, unit_id)
    expires_at = body.expires_at or now + (
        timedelta(hours=body.hours) if body.hours else inv.DEFAULT_HOLD
    )
    try:
        await inv.hold_unit(
            db,
            unit,
            actor=user,
            expires_at=expires_at,
            lead=lead,
            note=body.note,
            request=request,
            now=now,
        )
    except inv.InventoryRuleError as exc:
        raise _http(exc) from None
    await db.commit()
    return await _unit_response(db, unit)


@router.patch("/units/{unit_id}/release", response_model=UnitOut)
async def release(unit_id: int, request: Request, user: Manager, db: DbSession) -> UnitOut:
    unit = await _locked_unit(db, unit_id)
    try:
        await inv.release_unit(db, unit, actor=user, reason="manual", request=request)
    except inv.InventoryRuleError as exc:
        raise _http(exc) from None
    await db.commit()
    return await _unit_response(db, unit)
