from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.booking import BookingStatus, PaymentMode, PaymentPreference
from app.models.inventory import UnitType
from app.models.lead import LeadStatus
from app.schemas.channel_partner import PartnerBrief
from app.schemas.common import LongText, PlainText
from app.schemas.project import ProjectBrief
from app.schemas.user import UserBrief

Rupees = Annotated[int, Field(ge=0, le=10_000_000_000)]
Short = Annotated[PlainText, StringConstraints(max_length=150)]


Phone = Annotated[PlainText, StringConstraints(max_length=20, pattern=r"^[0-9+()\- ]{6,20}$")]
Email = Annotated[
    PlainText, StringConstraints(max_length=254, pattern=r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
]


class CustomerDetails(BaseModel):
    """Who the flat is booked for, and how they will pay. Bank details only with a bank loan."""

    model_config = ConfigDict(extra="forbid")
    customer_name: Short | None = None
    applicant_name: Short | None = None
    customer_mobile: Phone | None = None
    customer_email: Email | None = None
    customer_address: Annotated[PlainText, StringConstraints(max_length=500)] | None = None
    payment_preference: PaymentPreference | None = None
    bank_name: Short | None = None
    banker_name: Short | None = None
    banker_phone: Phone | None = None

    @model_validator(mode="after")
    def _bank(self) -> "CustomerDetails":
        if self.payment_preference != PaymentPreference.bank_loan and (
            self.bank_name or self.banker_name or self.banker_phone
        ):
            raise ValueError("Bank details only apply to bank payment")
        return self


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_id: int
    unit_id: int
    booking_date: date
    agreed_price: Annotated[int, Field(gt=0, le=10_000_000_000)]
    booking_amount: Rupees = 0
    payment_mode: PaymentMode | None = None
    payment_reference: Annotated[PlainText, StringConstraints(max_length=100)] | None = None
    channel_partner: Short | None = None
    notes: LongText | None = None
    sales_exec_id: int | None = (
        None  # managers/admins may credit someone else; default: the lead's owner
    )

    customer: CustomerDetails | None = None

    @model_validator(mode="after")
    def _amounts(self) -> "BookingCreate":
        if self.booking_amount > self.agreed_price:
            raise ValueError("The booking amount can't be more than the agreed price")
        return self


class BookingUpdate(BaseModel):
    """Managers and admins correct details. The flat can't change: cancel and book again."""

    model_config = ConfigDict(extra="forbid")
    booking_date: date | None = None
    agreed_price: Annotated[int, Field(gt=0, le=10_000_000_000)] | None = None
    booking_amount: Rupees | None = None
    payment_mode: PaymentMode | None = None
    payment_reference: Annotated[PlainText, StringConstraints(max_length=100)] | None = None
    channel_partner: Short | None = None
    notes: LongText | None = None
    sales_exec_id: int | None = None
    commission_expected: Rupees | None = None
    commission_received: Rupees | None = None


class BookingCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=255)]


class BookingLead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_code: str
    name: str
    mobile: str
    email: str | None
    city: str | None


class BookingUnit(BaseModel):
    id: int
    unit_no: str
    unit_type: UnitType
    building: str | None
    floor_number: int | None
    carpet_sqft: Decimal | None
    builtup_sqft: Decimal | None
    address_note: str | None


class BookingEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    at: datetime
    action: str
    actor: UserBrief | None
    details: dict[str, Any] | None


class BookingOut(BaseModel):
    id: int
    booking_code: str
    status: BookingStatus
    lead: BookingLead
    project: ProjectBrief
    unit: BookingUnit
    booking_date: date
    agreed_price: int
    booking_amount: int
    balance: int  # agreed price - booking amount (payment demands come in Phase 3)
    payment_mode: PaymentMode | None
    payment_reference: str | None
    channel_partner: str | None
    partner: PartnerBrief | None = None
    commission_pct: Decimal | None
    commission_expected: int | None
    commission_received: int
    notes: str | None
    sales_exec: UserBrief | None
    recorded_by: UserBrief | None
    customer: CustomerDetails
    created_at: datetime
    cancelled_at: datetime | None
    cancellation_reason: str | None
    history: list[BookingEventOut] = []


class MissingDetails(BaseModel):
    """A lead marked Booked (by status, or before bookings existed) with no booking record."""

    lead_id: int
    lead_code: str
    name: str
    mobile: str
    project: ProjectBrief | None
    assigned_to: UserBrief | None
    booked_since: datetime
    status: LeadStatus = LeadStatus.booked


class BookingTotals(BaseModel):
    count: int
    agreed_value: int
    booking_amount: int
    commission_expected: int
    commission_received: int


class BookingQuery(BaseModel):
    status: BookingStatus | None = BookingStatus.booked
    project_id: int | None = None
    sales_exec_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 50


class BookingPage(BaseModel):
    items: list[BookingOut]
    total: int
    page: int
    page_size: int
    totals: BookingTotals
    missing_details: list[MissingDetails]
