from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.inventory import UnitStatus, UnitType
from app.schemas.common import PlainText
from app.schemas.project import ProjectOut, UnitCounts
from app.schemas.user import UserBrief

UnitNo = Annotated[PlainText, StringConstraints(max_length=20)]
Sqft = Annotated[Decimal, Field(gt=0, le=100_000, max_digits=8, decimal_places=2)]
Rupees = Annotated[int, Field(ge=0, le=10_000_000_000)]


class _Areas(BaseModel):
    carpet_sqft: Sqft | None = None
    builtup_sqft: Sqft | None = None

    @model_validator(mode="after")
    def _builtup_not_smaller(self):
        if self.carpet_sqft and self.builtup_sqft and self.builtup_sqft < self.carpet_sqft:
            raise ValueError("Built-up area can't be smaller than carpet area")
        return self


class BuildingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[PlainText, StringConstraints(max_length=100)]
    sort_order: int = 0


class BuildingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[PlainText, StringConstraints(max_length=100)] | None = None
    sort_order: int | None = None


class FloorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: Annotated[int, Field(ge=-5, le=120)]


class GenerateUnits(_Areas):
    """Bulk-create floors and units: e.g. floors 1-4 with 6 units each -> 101..106 ... 401..406."""

    model_config = ConfigDict(extra="forbid")
    floor_from: Annotated[int, Field(ge=-5, le=120)] = 1
    floor_to: Annotated[int, Field(ge=-5, le=120)]
    units_per_floor: Annotated[int, Field(ge=1, le=20)]
    unit_type: UnitType
    base_price: Rupees | None = None

    @model_validator(mode="after")
    def _sane(self) -> "GenerateUnits":
        if self.floor_to < self.floor_from:
            raise ValueError("The top floor can't be below the first floor")
        if (self.floor_to - self.floor_from + 1) * self.units_per_floor > 600:
            raise ValueError("That's more than 600 units at once. Generate in smaller batches")
        return self


class UnitCreate(_Areas):
    model_config = ConfigDict(extra="forbid")
    unit_no: UnitNo
    unit_type: UnitType
    # Developer projects: the floor it's on. Resale listings: leave empty.
    floor_id: int | None = None
    base_price: Rupees | None = None
    current_asking_price: Rupees | None = None
    address_note: Annotated[PlainText, StringConstraints(max_length=200)] | None = None


class UnitUpdate(_Areas):
    model_config = ConfigDict(extra="forbid")
    unit_no: UnitNo | None = None
    unit_type: UnitType | None = None
    base_price: Rupees | None = None
    current_asking_price: Rupees | None = None
    # Rate per sq ft of saleable area; the asking price is worked out from it
    rate_psf: Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=2)] | None = None
    address_note: Annotated[PlainText, StringConstraints(max_length=200)] | None = None
    # Admins may set these by hand; On hold and Booked have their own flows.
    status: Literal[UnitStatus.available, UnitStatus.withdrawn, UnitStatus.sold] | None = None


class HoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Either a number of hours (default 48) or an exact end time
    hours: Annotated[int, Field(ge=1, le=14 * 24)] | None = None
    expires_at: AwareDatetime | None = None
    lead_id: int | None = None
    note: Annotated[PlainText, StringConstraints(max_length=255)] | None = None

    @model_validator(mode="after")
    def _one_way(self) -> "HoldRequest":
        if self.hours is not None and self.expires_at is not None:
            raise ValueError("Give either hours or an end time, not both")
        return self


class HeldLead(BaseModel):
    id: int
    name: str
    lead_code: str


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    building_id: int | None
    floor_id: int | None
    floor_number: int | None = None
    unit_no: str
    unit_type: UnitType
    carpet_sqft: Decimal | None
    builtup_sqft: Decimal | None
    base_price: int | None
    current_asking_price: int | None
    address_note: str | None
    status: UnitStatus
    hold_expired: bool = False
    held_by: UserBrief | None
    held_for: HeldLead | None = None
    held_at: datetime | None
    hold_expires_at: datetime | None
    hold_note: str | None
    booking_id: int | None = None
    rate_psf: Decimal | None = None


class FloorOut(BaseModel):
    id: int
    number: int
    units: list[UnitOut]


class BuildingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    sort_order: int


class BuildingTree(BuildingOut):
    counts: UnitCounts
    floors: list[FloorOut]  # top floor first, as on a building elevation


class Inventory(BaseModel):
    project: ProjectOut
    counts: UnitCounts
    buildings: list[BuildingTree]
    # Resale units (no building/floor)
    listings: list[UnitOut]
