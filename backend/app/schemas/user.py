from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.user import Role
from app.schemas.common import Email, NewPassword, PlainText

FullName = Annotated[PlainText, StringConstraints(max_length=150)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    full_name: FullName
    role: Role
    password: NewPassword


class UserUpdate(BaseModel):
    """Admin edit. Only the fields sent are changed. Setting password resets it."""

    model_config = ConfigDict(extra="forbid")

    full_name: FullName | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: NewPassword | None = None


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: NewPassword
