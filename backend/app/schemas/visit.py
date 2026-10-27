from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.models.task import TaskType
from app.models.visit import InterestLevel, VisitSource, VisitStatus
from app.schemas.common import LongText, PlainText
from app.schemas.project import ProjectBrief
from app.schemas.task import TaskLead
from app.schemas.user import UserBrief

Reason = Annotated[PlainText, StringConstraints(max_length=255)]
VisitView = Literal["upcoming", "completed", "missed", "all"]


class VisitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: int
    project_id: int
    scheduled_at: AwareDatetime
    visit_source: VisitSource = VisitSource.sales_follow_up
    notes: LongText | None = None
    # Managers/admins may choose who shows the site; executives host their own visits.
    host_id: int | None = None


class VisitComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: Annotated[LongText, StringConstraints(min_length=1)]
    interest_level: InterestLevel
    next_action: Reason | None = None
    follow_up_at: AwareDatetime | None = None
    follow_up_type: TaskType = TaskType.call


class VisitReschedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: AwareDatetime
    reason: Reason | None = None


class VisitNoShow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Reason | None = None


class VisitCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead: TaskLead
    project: ProjectBrief
    host: UserBrief | None
    visit_source: VisitSource
    scheduled_at: datetime
    status: VisitStatus
    # Scheduled time has passed but nobody recorded what happened.
    needs_update: bool = False
    notes: str | None
    reschedule_count: int
    feedback: str | None
    interest_level: InterestLevel | None
    next_action: str | None
    closed_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime


class VisitQuery(BaseModel):
    view: VisitView = "upcoming"
    project_id: int | None = None
    host_id: int | None = None
    mine: bool = False
    date_from: date | None = None
    date_to: date | None = None
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 50


class VisitCounts(BaseModel):
    upcoming: int
    needs_update: int


class VisitPage(BaseModel):
    items: list[VisitOut]
    total: int
    page: int
    page_size: int
    counts: VisitCounts
