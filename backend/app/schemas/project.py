from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.common import PlainText

ProjectName = Annotated[PlainText, StringConstraints(max_length=150)]


class ProjectBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class ProjectOut(ProjectBrief):
    is_active: bool


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ProjectName


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ProjectName | None = None
    is_active: bool | None = None
