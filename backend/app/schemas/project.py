from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.project import ProjectStatus, ProjectType
from app.schemas.common import LongText, PlainText

CommissionPct = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
ProjectName = Annotated[PlainText, StringConstraints(max_length=150)]
DeveloperName = Annotated[PlainText, StringConstraints(max_length=150)]


class ProjectBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class DeveloperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class DeveloperCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: DeveloperName


class UnitCounts(BaseModel):
    total: int = 0
    available: int = 0
    on_hold: int = 0
    booked: int = 0
    sold: int = 0
    withdrawn: int = 0


class ProjectOut(ProjectBrief):
    is_active: bool
    project_type: ProjectType
    status: ProjectStatus
    developer: DeveloperOut | None
    location: str | None
    description: str | None
    commission_pct: Decimal | None = None
    created_at: datetime


class ProjectWithCounts(ProjectOut):
    units: UnitCounts = UnitCounts()


class _DeveloperChoice(BaseModel):
    """Pick an existing developer by id, or type a new name to create one."""

    developer_id: int | None = None
    developer_name: DeveloperName | None = None

    @model_validator(mode="after")
    def _one_developer_source(self):
        if self.developer_id is not None and self.developer_name:
            raise ValueError("Choose an existing developer or type a new one, not both")
        return self


class ProjectCreate(_DeveloperChoice):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    project_type: ProjectType = ProjectType.developer
    status: ProjectStatus = ProjectStatus.under_construction
    location: Annotated[PlainText, StringConstraints(max_length=200)] | None = None
    description: LongText | None = None
    commission_pct: CommissionPct | None = None

    @model_validator(mode="after")
    def _developer_matches_type(self) -> "ProjectCreate":
        has_dev = self.developer_id is not None or bool(self.developer_name)
        if self.project_type == ProjectType.developer and not has_dev:
            raise ValueError("A developer project needs its developer")
        if self.project_type == ProjectType.resale and has_dev:
            raise ValueError("Resale listings don't have a developer")
        return self


class ProjectUpdate(_DeveloperChoice):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName | None = None
    is_active: bool | None = None
    project_type: ProjectType | None = None
    status: ProjectStatus | None = None
    location: Annotated[PlainText, StringConstraints(max_length=200)] | None = None
    description: LongText | None = None
    commission_pct: CommissionPct | None = None
