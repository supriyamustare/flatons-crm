from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.schemas.common import Email


class LoginRequest(BaseModel):
    email: Email
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
