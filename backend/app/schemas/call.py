from datetime import date, datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.call import CallDirection, CallOutcome
from app.models.task import TaskType
from app.schemas.common import LongText
from app.schemas.task import TaskLead
from app.schemas.user import UserBrief


class CallCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: int
    outcome: CallOutcome
    direction: CallDirection = CallDirection.outgoing
    duration_sec: Annotated[int, Field(ge=0, le=4 * 3600)] | None = None
    notes: LongText | None = None
    # When the call happened; defaults to now. Can't be in the future.
    called_at: AwareDatetime | None = None
    # Setting a next date creates a follow-up task automatically.
    follow_up_at: AwareDatetime | None = None
    follow_up_type: TaskType = TaskType.call
    # Logging the call from a follow-up can close that follow-up in the same step.
    complete_task_id: int | None = None


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead: TaskLead
    user: UserBrief | None
    direction: CallDirection
    outcome: CallOutcome
    connected: bool = False
    duration_sec: int | None
    notes: str | None
    called_at: datetime
    follow_up_task_id: int | None


class CallQuery(BaseModel):
    """Query-string filters: ids, dates and fixed values only, never personal data."""

    user_id: int | None = None
    mine: bool = False
    outcome: CallOutcome | None = None
    lead_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 50


class CallPage(BaseModel):
    items: list[CallOut]
    total: int
    page: int
    page_size: int
    connected: int  # how many of `total` were connected, for a quick connection rate
