from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.lead import LeadStatus
from app.schemas.common import LongText, Mobile, PlainText
from app.schemas.user import UserBrief

Short = Annotated[PlainText, StringConstraints(max_length=150)]
Email = Annotated[
    PlainText, StringConstraints(max_length=254, pattern=r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
]
Rera = Annotated[PlainText, StringConstraints(max_length=50, pattern=r"^[A-Za-z0-9/\- ]{4,50}$")]


class PartnerBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    company_name: str | None


class PartnerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Short
    company_name: Short | None = None
    mobile: Mobile
    email: Email | None = None
    rera_number: Rera | None = None
    notes: LongText | None = None


class PartnerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Short | None = None
    company_name: Short | None = None
    mobile: Mobile | None = None
    email: Email | None = None
    rera_number: Rera | None = None
    notes: LongText | None = None
    is_active: bool | None = None


class PartnerOut(BaseModel):
    """leads / bookings / booked_value: customers this partner brought (bookings = live bookings)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    company_name: str | None
    mobile: str
    email: str | None
    rera_number: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    leads: int = 0
    bookings: int = 0
    booked_value: int = 0


class PartnerCustomer(BaseModel):
    lead_id: int
    lead_code: str
    name: str
    mobile: str
    status: LeadStatus
    project: str | None
    owner: UserBrief | None
    created_at: datetime
    booking_id: int | None = None
    booking_code: str | None = None
    unit_no: str | None = None
    booked_project: str | None = None
    agreed_price: int | None = None
    booking_date: date | None = None


class PartnerCustomers(BaseModel):
    items: list[PartnerCustomer]
    total: int


class PartnerQuery(BaseModel):
    q: Annotated[str, StringConstraints(max_length=80)] | None = (
        None  # name, company or RERA (no phone numbers in URLs)
    )
    include_inactive: bool = False
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=200)] = 50
