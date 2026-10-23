"""Reusable validated field types."""

import re
from typing import Annotated

from pydantic import AfterValidator, EmailStr, StringConstraints

_HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z!]")


def _no_html(value: str) -> str:
    """Reject HTML tags but allow ordinary use of < and >, e.g. "budget < 50L"."""
    if _HTML_TAG.search(value):
        raise ValueError("must not contain HTML")
    return value


def _bcrypt_limit(value: str) -> str:
    if len(value.encode()) > 72:
        raise ValueError("must be at most 72 bytes")
    return value


Email = Annotated[EmailStr, AfterValidator(str.lower)]

PlainText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1), AfterValidator(_no_html)
]

# Free text such as remarks and notes: HTML rejected, may be long, blank allowed
LongText = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=5000), AfterValidator(_no_html)
]


def normalize_mobile(value: str) -> str:
    """Return a phone number as +<country><number>. Indian numbers can be typed as
    98765 43210, 09876543210, +91-98765-43210, etc."""
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        if not 8 <= len(digits) <= 15:
            raise ValueError("enter a valid phone number")
        if digits.startswith("91") and not re.fullmatch(r"91[6-9]\d{9}", digits):
            raise ValueError("enter a valid 10-digit Indian mobile number")
        return f"+{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ValueError("enter a valid 10-digit Indian mobile number")
    return f"+91{digits}"


Mobile = Annotated[str, AfterValidator(normalize_mobile)]

NewPassword = Annotated[
    str, StringConstraints(min_length=8, max_length=72), AfterValidator(_bcrypt_limit)
]
