from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.booking import Booking, BookingStatus
from app.models.inventory import Building, Floor, Unit, UnitStatus
from app.models.project import Project
from app.models.user import Role, User
from app.schemas.common import PlainText
from app.services import cost_sheet as cs
from app.services.audit import log_audit

router = APIRouter(tags=["cost sheets"])
Viewer = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive, Role.docs))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]
Admin = Annotated[User, Depends(require_role(Role.admin))]
Pct = Annotated[float, Field(ge=0, le=100)]
Money = Annotated[int, Field(ge=0, le=100_000_000)]
Text = Annotated[PlainText, StringConstraints(max_length=300)]


class StageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[PlainText, StringConstraints(min_length=1, max_length=80)]
    pct: Annotated[float, Field(gt=0, le=100)]


class TemplateIn(BaseModel):
    """The project's cost sheet: shown on every unit's cost sheet unless the unit overrides a number."""

    model_config = ConfigDict(extra="forbid")
    developer_name: Text | None = None
    site_address: Text | None = None
    rera_number: Annotated[PlainText, StringConstraints(max_length=80)] | None = None
    gst_pct: Pct = 1.0
    stamp_duty_pct: Pct = 7.0
    registration_pct: Pct = 1.0
    registration_cap: Money = 30000
    legal_charges: Money = 10000
    furnishing_per_sqft: Annotated[float, Field(ge=0, le=100_000)] = 0
    stages: Annotated[list[StageIn], Field(min_length=1, max_length=40)]
    notes: Annotated[list[Text], Field(max_length=30)] = []
    signatory: Annotated[PlainText, StringConstraints(max_length=120)] | None = None

    @field_validator("developer_name", "site_address", "rera_number", "signatory", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode="after")
    def _stages_total(self) -> "TemplateIn":
        total = round(sum(s.pct for s in self.stages), 4)
        if total != 100:
            raise ValueError(f"Payment stages must add up to 100% (now {total:g}%)")
        return self


class UnitCostIn(BaseModel):
    """A unit's own numbers. Leave a field out (or null) to use the project's value."""

    model_config = ConfigDict(extra="forbid")
    rate_psf: Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=2)] | None = None
    chargeable_sqft: Annotated[float, Field(gt=0, le=100_000)] | None = None
    gst_pct: Pct | None = None
    stamp_duty_pct: Pct | None = None
    registration_pct: Pct | None = None
    registration_cap: Money | None = None
    legal_charges: Money | None = None
    furnishing_per_sqft: Annotated[float, Field(ge=0, le=100_000)] | None = None
    other_charges: Money | None = None
    other_charges_label: Annotated[PlainText, StringConstraints(max_length=80)] | None = None


async def _unit(db: DbSession, unit_id: int) -> Unit:
    unit = await db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")
    return unit


async def build(db: DbSession, unit: Unit) -> cs.CostSheet:
    project = await db.get(Project, unit.project_id)
    building = await db.get(Building, unit.building_id) if unit.building_id else None
    floor = await db.get(Floor, unit.floor_id) if unit.floor_id else None
    label = " / ".join(
        p
        for p in (
            building.name if building else None,
            ("Ground floor" if floor and floor.number == 0 else f"Floor {floor.number}")
            if floor
            else None,
            f"Unit {unit.unit_no}",
            unit.unit_type.value.replace("bhk", " BHK").title(),
        )
        if p
    )
    customer = None
    if unit.status == UnitStatus.booked:
        b = await db.scalar(
            select(Booking).where(
                Booking.unit_id == unit.id, Booking.status == BookingStatus.booked
            )
        )
        if b is not None:
            customer = {
                "name": b.customer_name or b.lead.name,
                "applicant_name": b.applicant_name,
                "mobile": b.customer_mobile or b.lead.mobile,
                "email": b.customer_email or b.lead.email,
                "address": b.customer_address,
                "booking_code": f"BKG-{b.id:05d}",
                "booking_date": b.booking_date.isoformat(),
                "agreed_price": b.agreed_price,
                "payment_preference": b.payment_preference.value if b.payment_preference else None,
                "bank_name": b.bank_name,
            }
    # A booked unit's cost sheet uses the agreed price
    rate = float(unit.rate_psf) if unit.rate_psf else None
    price = unit.current_asking_price or unit.base_price
    if customer:
        rate, price = None, customer["agreed_price"]
    return cs.compute(
        project_name=project.name,
        template=project.cost_sheet,
        overrides=unit.cost_sheet,
        unit_no=unit.unit_no,
        unit_label=label,
        carpet_sqft=float(unit.carpet_sqft) if unit.carpet_sqft else None,
        builtup_sqft=float(unit.builtup_sqft) if unit.builtup_sqft else None,
        rate_psf=rate,
        asking_price=price,
        customer=customer,
    )


@router.get("/units/{unit_id}/cost-sheet", response_model=cs.CostSheet)
async def unit_cost_sheet(unit_id: int, _: Viewer, db: DbSession) -> cs.CostSheet:
    return await build(db, await _unit(db, unit_id))


@router.put("/units/{unit_id}/cost-sheet", response_model=cs.CostSheet)
async def edit_unit_cost_sheet(
    unit_id: int, body: UnitCostIn, request: Request, user: Manager, db: DbSession
) -> cs.CostSheet:
    """Replace this unit's own numbers (rate and any overrides). Sending {} goes back to the project's values."""
    unit = await _unit(db, unit_id)
    data = body.model_dump(exclude_none=True)
    rate = data.pop("rate_psf", None)
    before = {"rate_psf": str(unit.rate_psf), "overrides": unit.cost_sheet}
    unit.cost_sheet = data or None
    if "rate_psf" in body.model_fields_set:
        unit.rate_psf = rate
        area = data.get("chargeable_sqft") or unit.builtup_sqft or unit.carpet_sqft
        if rate and area:
            unit.current_asking_price = int(round(float(rate) * float(area)))
    log_audit(
        db,
        action="unit.cost_sheet",
        entity_type="unit",
        entity_id=unit.id,
        actor=user,
        details={
            "from": before,
            "to": {"rate_psf": str(unit.rate_psf), "overrides": unit.cost_sheet},
        },
        request=request,
    )
    await db.commit()
    await db.refresh(unit)
    return await build(db, unit)


@router.get("/projects/{project_id}/cost-sheet", response_model=TemplateIn)
async def project_template(project_id: int, _: Viewer, db: DbSession) -> TemplateIn:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return TemplateIn.model_validate(cs.merged(project.cost_sheet, None))


@router.put("/projects/{project_id}/cost-sheet", response_model=TemplateIn)
async def edit_project_template(
    project_id: int, body: TemplateIn, request: Request, admin: Admin, db: DbSession
) -> TemplateIn:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    project.cost_sheet = body.model_dump()
    log_audit(
        db,
        action="project.cost_sheet",
        entity_type="project",
        entity_id=project.id,
        actor=admin,
        request=request,
    )
    await db.commit()
    return body
