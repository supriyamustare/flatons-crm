from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.marketing import Channel
from app.models.visit import VisitSource
from app.schemas.project import ProjectBrief
from app.schemas.user import UserBrief

RangeKey = Literal["today", "7d", "30d", "custom"]
Rate = float | None  # None = "N/A" (nothing to divide by), never shown as 0%


class ReportQuery(BaseModel):
    range: RangeKey = "30d"
    date_from: date | None = None
    date_to: date | None = None
    project_id: int | None = None
    user_id: int | None = None  # managers/admins only; executives always see themselves

    @model_validator(mode="after")
    def _custom(self) -> "ReportQuery":
        if self.range == "custom":
            if not (self.date_from and self.date_to):
                raise ValueError("Choose both a start and an end date")
            if self.date_from > self.date_to:
                raise ValueError("The start date must be before the end date")
            if (self.date_to - self.date_from).days > 366:
                raise ValueError("Choose a range of one year or less")
        return self


class Period(BaseModel):
    date_from: date
    date_to: date
    scope: Literal["team", "mine", "person"]
    definitions: dict[str, str]


# ---- calls
class CallRow(BaseModel):
    user: UserBrief | None
    calls: int
    connected: int
    connection_rate: Rate
    talk_minutes: int


class CallDay(BaseModel):
    day: date
    calls: int
    connected: int


class CallsReport(Period):
    rows: list[CallRow]
    totals: CallRow
    by_day: list[CallDay]


# ---- visits
class VisitCounts(BaseModel):
    visits: int  # all visits dated in the period, any status
    completed: int
    no_show: int
    cancelled: int
    scheduled: int  # still awaiting an outcome
    completion_rate: Rate


class VisitByProject(VisitCounts):
    project: ProjectBrief


class VisitBySource(VisitCounts):
    source: VisitSource


class VisitByPerson(VisitCounts):
    user: UserBrief | None


class VisitsReport(Period):
    by_project: list[VisitByProject]
    by_source: list[VisitBySource]
    by_person: list[VisitByPerson]
    totals: VisitCounts


# ---- conversion
class Funnel(BaseModel):
    leads: int
    visited: int
    booked: int
    booked_after_visit: int
    visit_rate: Rate
    visit_to_booking_rate: Rate
    conversion_rate: Rate


class FunnelByPerson(Funnel):
    user: UserBrief | None


class FunnelByProject(Funnel):
    project: ProjectBrief | None


class ConversionReport(Period):
    totals: Funnel
    by_person: list[FunnelByPerson]
    by_project: list[FunnelByProject]


# ---- campaigns
class CampaignRow(BaseModel):
    campaign_id: int | None
    name: str
    channel: Channel | None
    spend: int
    leads: int
    visited: int
    booked: int
    cost_per_lead: int | None
    cost_per_visit: int | None
    cost_per_booking: int | None


class CampaignsReport(Period):
    rows: list[CampaignRow]
    totals: CampaignRow
    unattributed_leads: int


# ---- staff
class StaffRow(BaseModel):
    user: UserBrief
    leads: int
    calls: int
    connected: int
    connection_rate: Rate
    visits_completed: int
    bookings: int
    lead_to_booking_rate: Rate


class StaffReport(Period):
    rows: list[StaffRow]
    totals: StaffRow


ReportKind = Literal["calls", "visits", "conversion", "campaigns", "staff"]
CsvSection = Annotated[str, Field(max_length=40)]
