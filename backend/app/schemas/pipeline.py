from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.lead import LeadStatus
from app.schemas.project import ProjectBrief
from app.schemas.user import UserBrief


class PipelineQuery(BaseModel):
    """Query-string filters: ids, dates and flags only (no personal data in URLs)."""

    project_id: int | None = None
    assigned_to_id: int | None = None
    mine: bool = False
    created_from: date | None = None
    created_to: date | None = None
    include_closed: bool = False  # also show Lost and Junk columns
    stale_only: bool = False
    per_stage: Annotated[int, Field(ge=1, le=200)] = 50


class PipelineCard(BaseModel):
    id: int
    lead_code: str
    name: str
    status: LeadStatus
    project: ProjectBrief | None
    budget_min: int | None
    budget_max: int | None
    deal_value: int | None
    assigned_to: UserBrief | None
    days_in_stage: int
    stale: bool
    last_activity_at: datetime


class StageColumn(BaseModel):
    """One kanban column. value = sum of deal values; weighted = value x probability."""

    stage: LeadStatus
    probability_pct: int
    count: int
    value: int
    weighted_value: int
    stale_count: int
    missing_value_count: int  # leads with neither an estimated value nor a budget
    cards: list[PipelineCard]
    has_more: bool


class PipelineTotals(BaseModel):
    """Open = every stage except Booked, Lost and Junk."""

    open_count: int
    open_value: int
    weighted_value: int
    booked_count: int
    booked_value: int
    stale_count: int
    missing_value_count: int


class PipelineBoard(BaseModel):
    stale_after_days: int
    stages: list[StageColumn]
    totals: PipelineTotals


class ForecastRow(BaseModel):
    count: int
    value: int
    weighted_value: int


class ProjectForecast(ForecastRow):
    project: ProjectBrief | None  # None = leads with no project chosen


class ExecutiveForecast(ForecastRow):
    user: UserBrief | None  # None = unassigned leads


class Forecast(BaseModel):
    by_project: list[ProjectForecast]
    by_executive: list[ExecutiveForecast]
    total: ForecastRow


class StageProbability(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    stage: LeadStatus
    probability_pct: Annotated[int, Field(ge=0, le=100)]


class ProbabilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stages: Annotated[list[StageProbability], Field(min_length=1, max_length=13)]

    @model_validator(mode="after")
    def _sane(self) -> "ProbabilityUpdate":
        seen = [s.stage for s in self.stages]
        if len(seen) != len(set(seen)):
            raise ValueError("Each stage can appear only once")
        fixed = {LeadStatus.booked: 100, LeadStatus.lost: 0, LeadStatus.junk: 0}
        for s in self.stages:
            if s.stage in fixed and s.probability_pct != fixed[s.stage]:
                raise ValueError(f"{s.stage.value} is always {fixed[s.stage]}%")
        return self
