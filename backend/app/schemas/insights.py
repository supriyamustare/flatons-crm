from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.models.inventory import UnitType
from app.models.lead import LeadSource
from app.schemas.user import UserBrief


class ProjectStock(BaseModel):
    """sold = agreement_done + booked; blocked = On hold; available = Available (Withdrawn left out)."""

    id: int
    name: str
    location: str | None
    project_type: str
    unit_types: list[UnitType]
    price_min: int | None  # asking price, else base price, of units still for sale
    price_max: int | None
    sold: int
    agreement_done: int = 0
    booked: int = 0
    blocked: int
    available: int
    total: int
    sold_pct: float | None
    bookings_this_month: int
    booked_value_this_month: int


class StatusSlice(BaseModel):
    key: Literal["working", "quiet", "unassigned", "booked", "dead"]
    count: int


class OwnerCount(BaseModel):
    user: UserBrief | None  # None = unassigned
    count: int


class Scheduled(BaseModel):
    key: str  # "site_visit" or a follow-up type
    count: int


class MonthPoint(BaseModel):
    month: date  # first day of the month
    leads: int
    deals: int


class SourceRow(BaseModel):
    source: LeadSource
    leads: int
    sales: int
    conversion: float | None


class RecentBooking(BaseModel):
    id: int
    booking_code: str
    customer: str
    project: str
    unit_no: str
    agreed_price: int
    booking_date: date
    sales_exec: UserBrief | None


class Insights(BaseModel):
    """Definitions:

    projects            active projects; inventory counts are always company-wide
    lead_status         open leads split by: working (activity in the last 7 days), quiet (7+ days),
                        unassigned (no owner); plus booked and dead (Lost/Junk). All leads, not deleted.
    waiting_by_owner    New leads with no call yet, per owner
    scheduled_30d       site visits still scheduled and pending follow-ups (by type), next 30 days
    months              last 12 months: leads created, and deals = live bookings by booking date plus
                        leads marked Booked without a booking record (by when they became Booked)
    sources             leads created in the last 12 months by source; sales = those now Booked
    first_response_min  median minutes from a lead arriving to its first call, leads created this month
                        and called; None when there are none
    """

    projects: list[ProjectStock]
    lead_status: list[StatusSlice]
    total_leads: int
    waiting_by_owner: list[OwnerCount]
    scheduled_30d: list[Scheduled]
    months: list[MonthPoint]
    sources: list[SourceRow]
    first_response_min: int | None
    contacted_within_day_pct: float | None
    recent_bookings: list[RecentBooking]
