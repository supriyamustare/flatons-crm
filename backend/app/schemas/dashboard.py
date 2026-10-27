from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from app.models.lead import LeadStatus
from app.schemas.task import TaskOut
from app.schemas.user import UserBrief
from app.schemas.visit import VisitOut

RangeKey = Literal["today", "7d", "30d", "custom"]


class DashboardQuery(BaseModel):
    range: RangeKey = "7d"
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _custom_needs_dates(self) -> "DashboardQuery":
        if self.range == "custom":
            if not (self.date_from and self.date_to):
                raise ValueError("Choose both a start and an end date")
            if self.date_from > self.date_to:
                raise ValueError("The start date must be before the end date")
            if (self.date_to - self.date_from).days > 366:
                raise ValueError("Choose a range of one year or less")
        return self


class Kpis(BaseModel):
    """Every number's exact definition (scope = everyone for admin/manager, own for executive):

    total_leads        leads not deleted, any date
    new_leads          leads created in the period
    follow_ups_today   open follow-ups due today (India time), including today's late ones
    overdue_follow_ups open follow-ups whose due time has passed (any day)
    visits_scheduled   visits whose date is in the period, excluding cancelled
    visits_completed   visits whose date is in the period and were completed
    calls              calls made in the period
    calls_connected    of those, where the customer answered
    connection_rate    calls_connected / calls, or None when there were no calls
    """

    total_leads: int
    new_leads: int
    follow_ups_today: int
    overdue_follow_ups: int
    visits_scheduled: int
    visits_completed: int
    calls: int
    calls_connected: int
    connection_rate: float | None


class ActivityFeedItem(BaseModel):
    id: int
    type: str
    note: str | None
    details: dict[str, Any] | None
    actor: UserBrief | None
    lead_id: int
    lead_name: str
    lead_code: str
    created_at: datetime


class Business(BaseModel):
    """Company figures for the period (Team view only). Definitions:

    leads_generated   leads created in the period
    leads_booked      leads that moved to Booked in the period ("leads done")
    revenue           commission on booked leads: the booking's expected commission (agreed price x
                      project %) where a booking is recorded, else deal value x project % (deal
                      value = estimated value, else top of budget, else bottom)
    expense           marketing expenses dated in the period
    profit            revenue - expense (estimated)
    unvalued_bookings booked leads left out of revenue (no project, no commission % or no value)
    """

    leads_generated: int
    leads_booked: int
    booking_rate: float | None
    revenue: int
    expense: int
    profit: int
    unvalued_bookings: int


class TeamMember(BaseModel):
    """One sales person's figures (Team view only). Definitions:

    calls_today       calls they logged today (India time), whatever the period
    calls / connected calls they logged in the period / of those, answered
    visits_done       completed site visits they hosted, dated in the period
    converted         their leads that moved to Booked in the period
    dead              their leads that moved to Lost or Junk in the period
    closing_rate      converted / (converted + dead); None when nothing closed
    open_leads        leads assigned to them now, not Booked/Lost/Junk
    overdue           their open follow-ups past due right now
    """

    user: UserBrief
    calls_today: int
    calls: int
    connected: int
    connection_rate: float | None
    visits_done: int
    converted: int
    dead: int
    closing_rate: float | None
    open_leads: int
    overdue: int


class Dashboard(BaseModel):
    scope: Literal["team", "mine"]
    date_from: date
    date_to: date
    kpis: Kpis
    leads_by_status: dict[LeadStatus, int]
    overdue: list[TaskOut]
    visits_needing_update: list[VisitOut]
    activity: list[ActivityFeedItem]
    business: Business | None = None
    team: list[TeamMember] | None = None
