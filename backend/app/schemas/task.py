from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.models.task import TaskStatus, TaskType
from app.schemas.common import LongText, PlainText
from app.schemas.user import UserBrief

TaskView = Literal["today", "overdue", "upcoming", "completed"]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: int
    task_type: TaskType
    # Must include a timezone (the app sends e.g. 2026-10-24T10:00:00+05:30).
    due_at: AwareDatetime
    notes: LongText | None = None
    # Managers/admins may give the task to someone else; executives always own theirs.
    assigned_to_id: int | None = None


class TaskComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completion_note: Annotated[LongText, StringConstraints(min_length=1)]


class TaskReschedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_at: AwareDatetime
    reason: Annotated[PlainText, StringConstraints(max_length=255)] | None = None


class TaskLead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_code: str
    name: str
    mobile: str


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead: TaskLead
    task_type: TaskType
    due_at: datetime
    status: TaskStatus
    is_overdue: bool = False
    notes: str | None
    completion_note: str | None
    completed_at: datetime | None
    rescheduled_from_id: int | None
    reschedule_reason: str | None
    assigned_to: UserBrief | None
    created_by: UserBrief | None
    created_at: datetime


class TaskCounts(BaseModel):
    today: int
    overdue: int
    upcoming: int


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    page_size: int
    counts: TaskCounts


class TaskQuery(BaseModel):
    """Query-string filters. Only ids and fixed values, never personal data."""

    view: TaskView = "today"
    task_type: TaskType | None = None
    assigned_to_id: int | None = None
    mine: bool = False
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 50
