"""Reusable validated field types."""

from typing import Annotated

from pydantic import AfterValidator, EmailStr, StringConstraints


def _no_html(value: str) -> str:
    if "<" in value or ">" in value:
        raise ValueError("must not contain < or >")
    return value


def _bcrypt_limit(value: str) -> str:
    if len(value.encode()) > 72:
        raise ValueError("must be at most 72 bytes")
    return value


Email = Annotated[EmailStr, AfterValidator(str.lower)]

PlainText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1), AfterValidator(_no_html)
]

NewPassword = Annotated[
    str, StringConstraints(min_length=8, max_length=72), AfterValidator(_bcrypt_limit)
]
