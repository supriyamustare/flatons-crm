from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.lead import (
    ACTIVE_SOURCES,
    BuyingTimeline,
    Configuration,
    LeadSource,
    LeadStatus,
    Purpose,
)
from app.schemas.common import Email, LongText, Mobile, PlainText
from app.schemas.project import ProjectBrief
from app.schemas.user import UserBrief


class CampaignBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


Name = Annotated[PlainText, StringConstraints(max_length=150)]
ShortText = Annotated[PlainText, StringConstraints(max_length=150)]
Rupees = Annotated[int, Field(ge=0, le=10_000_000_000)]  # up to ₹1,000 crore


class _LeadFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alt_mobile: Mobile | None = None
    email: Email | None = None
    city: ShortText | None = None
    sub_source: ShortText | None = None
    project_id: int | None = None
    campaign_id: int | None = None
    configuration: Configuration | None = None
    budget_min: Rupees | None = None
    budget_max: Rupees | None = None
    purpose: Purpose | None = None
    timeline: BuyingTimeline | None = None
    estimated_value: Rupees | None = None
    remarks: LongText | None = None

    @model_validator(mode="after")
    def _budget_range(self) -> "_LeadFields":
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError("Minimum budget can't be more than maximum budget")
        return self


class LeadCreate(_LeadFields):
    name: Name
    mobile: Mobile
    source: LeadSource

    @field_validator("source")
    @classmethod
    def _active_source(cls, v: LeadSource) -> LeadSource:
        if v not in ACTIVE_SOURCES:
            raise ValueError(f"{v.value} is no longer used as a lead source")
        return v

    # Managers/admins may assign on creation; executives always own what they create.
    assigned_to_id: int | None = None


class LeadUpdate(_LeadFields):
    """Only fields that are sent are changed. Status and assignment have their own endpoints."""

    name: Name | None = None
    mobile: Mobile | None = None
    source: LeadSource | None = None


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LeadStatus
    reason: Annotated[PlainText, StringConstraints(max_length=255)] | None = None
    note: LongText | None = None


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assigned_to_id: int | None  # null = unassign


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Annotated[LongText, StringConstraints(min_length=1)]


class DuplicateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: Mobile | None = None
    alt_mobile: Mobile | None = None
    email: Email | None = None
    exclude_id: int | None = None


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_code: str
    name: str
    mobile: str
    alt_mobile: str | None
    email: str | None
    city: str | None
    source: LeadSource
    sub_source: str | None
    project: ProjectBrief | None
    campaign: CampaignBrief | None = None
    configuration: Configuration | None
    budget_min: int | None
    budget_max: int | None
    purpose: Purpose | None
    timeline: BuyingTimeline | None
    assigned_to: UserBrief | None
    status: LeadStatus
    lost_reason: str | None
    estimated_value: int | None
    remarks: str | None
    created_by: UserBrief | None
    last_activity_at: datetime
    created_at: datetime
    updated_at: datetime


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    note: str | None
    details: dict[str, Any] | None
    actor: UserBrief | None
    created_at: datetime


class LeadBooking(BaseModel):
    """The lead's live booking, if any."""

    id: int
    booking_code: str
    project: str
    unit_no: str
    agreed_price: int


class LeadDetail(LeadOut):
    activities: list[ActivityOut]
    can_edit: bool
    booking: LeadBooking | None = None


class DuplicateOut(BaseModel):
    id: int
    lead_code: str
    name: str
    status: LeadStatus
    assigned_to_name: str | None
    matched_on: list[Literal["mobile", "email"]]
    can_view: bool


class LeadCreated(BaseModel):
    lead: LeadOut
    duplicates: list[DuplicateOut]


SortField = Literal["created_at", "updated_at", "last_activity_at", "name"]


class LeadSearch(BaseModel):
    """Search and filters are sent in a POST body so phone numbers and names
    never appear in URLs or server logs."""

    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    statuses: list[LeadStatus] = []
    sources: list[LeadSource] = []
    project_id: int | None = None
    assigned_to_id: int | None = None
    unassigned: bool = False
    created_from: date | None = None
    created_to: date | None = None
    sort: SortField = "created_at"
    order: Literal["asc", "desc"] = "desc"
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 25


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int
    page: int
    page_size: int
