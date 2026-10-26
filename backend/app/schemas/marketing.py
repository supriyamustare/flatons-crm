from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.marketing import Channel, ExpenseCategory
from app.schemas.common import LongText, PlainText
from app.schemas.project import ProjectBrief
from app.schemas.user import UserBrief

Rupees = Annotated[int, Field(gt=0, le=1_000_000_000)]  # up to ₹100 crore per entry


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    channel: Channel
    project: ProjectBrief | None
    start_date: date
    end_date: date | None
    description: str | None
    created_at: datetime


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[PlainText, StringConstraints(max_length=150)]
    channel: Channel
    project_id: int | None = None
    start_date: date
    end_date: date | None = None
    description: LongText | None = None

    @model_validator(mode="after")
    def _dates(self) -> "CampaignCreate":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date can't be before the start date")
        return self


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    channel: Channel | None = None
    project_id: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: LongText | None = None


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    campaign: "CampaignBriefWithChannel"
    spent_on: date
    amount: int
    category: ExpenseCategory
    vendor: str | None
    notes: str | None
    has_receipt: bool = False
    receipt_name: str | None
    entered_by: UserBrief | None
    created_at: datetime


class CampaignBriefWithChannel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    channel: Channel


class ExpenseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: int | None = None
    spent_on: date | None = None
    amount: Rupees | None = None
    category: ExpenseCategory | None = None
    vendor: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    notes: Annotated[PlainText, StringConstraints(max_length=500)] | None = None


class ExpenseQuery(BaseModel):
    campaign_id: int | None = None
    channel: Channel | None = None
    project_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 50


class ExpensePage(BaseModel):
    items: list[ExpenseOut]
    total: int
    page: int
    page_size: int
    total_amount: int
    by_channel: dict[Channel, int]


ExpenseOut.model_rebuild()
