from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.models.lead import LeadSource, LeadStatus
from app.schemas.user import UserBrief

LeadTab = Literal["fresh", "today", "visit", "closing", "reengage"]


class WeekMonth(BaseModel):
    week: int
    month: int


class Trend(BaseModel):
    """Month to date vs the same days of last month, plus a daily series for the last 30 days."""

    month: int
    last_month: int
    change_pct: float | None  # None when last month was 0 (shown as "new")
    daily: list[int]


class Performance(BaseModel):
    enquiries: Trend
    site_visits: Trend
    sales: Trend
    calls: Trend
    spend: Trend | None  # team view only
    cost_per_sale: int | None  # spend this month / sales this month; team view only


class OverviewLead(BaseModel):
    id: int
    lead_code: str
    name: str
    mobile: str
    source: LeadSource
    status: LeadStatus
    city: str | None
    next_action: str | None  # "Follow-up" / "Site visit"
    next_at: datetime | None
    owner: UserBrief | None


class ThisMonth(BaseModel):
    new_leads: int
    active: int
    qualified: int
    unassigned: int
    active_rate: float | None
    win_rate: float | None


class Overview(BaseModel):
    """Definitions:

    in_closing        open leads in Negotiation
    fresh_waiting     leads still New with no call logged (waiting for first contact)
    followups_due     pending follow-ups due by the end of today (overdue included)
    visits_today      site visits scheduled today, still to happen
    visits_completed  completed site visits dated this week (Mon-today) / this month
    sales_closed      live bookings dated this week / this month
    sales_revenue     agreed price of those bookings
    enquiries         leads created (person: leads assigned to them)
    active            open leads with any activity this month; active_rate = active / open leads
    qualified         leads created this month now at Qualified or further (not Lost/Junk)
    win_rate          this month: booked / (booked + lost + junk) among leads closed this month
    """

    scope: Literal["team", "person"]
    person: UserBrief | None
    today: date
    in_closing: int
    fresh_waiting: int
    followups_due: int
    followups_overdue: int
    visits_today: int
    visits_completed: WeekMonth
    sales_closed: WeekMonth
    sales_revenue: WeekMonth
    performance: Performance
    tab_counts: dict[LeadTab, int]
    tab: LeadTab
    leads: list[OverviewLead]
    this_month: ThisMonth
    people: list[UserBrief]  # for the person picker (team view)
