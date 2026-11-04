"""Indian business identifiers, with plain-English error messages.

Values are tidied first (upper case, spaces and dashes removed), so "27aapfu 0939f1zv" is accepted as 27AAPFU0939F1ZV."""

import re
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator

_ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _tidy(v: object) -> object:
    if isinstance(v, str):
        v = re.sub(r"[\s\-]", "", v).upper()
        return v or None
    return v


def gstin_check_char(first14: str) -> str:
    """The official GSTIN check character (mod-36 checksum over the first 14 characters)."""
    total = 0
    for i, c in enumerate(first14):
        p = _ALNUM.index(c) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return _ALNUM[(36 - total % 36) % 36]


def _gstin(v: str) -> str:
    if len(v) != 15:
        raise ValueError(f"GSTIN must be 15 characters (this one has {len(v)})")
    if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}", v):
        raise ValueError(
            "GSTIN must be a 2-digit state code, the 10-character PAN (e.g. AAPFU0939F), then 3 letters or digits"
        )
    if gstin_check_char(v[:14]) != v[14]:
        raise ValueError(
            "This GSTIN's last character doesn't match the rest; please check it for a typo"
        )
    return v


def _pan(v: str) -> str:
    if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", v):
        raise ValueError(
            "PAN must be 10 characters: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)"
        )
    return v


def _ifsc(v: str) -> str:
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v):
        raise ValueError(
            "IFSC must be 11 characters: 4 letters, a zero, then 6 letters or digits (e.g. HDFC0001234)"
        )
    return v


def _cin(v: str) -> str:
    if not re.fullmatch(r"[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}", v):
        raise ValueError(
            "CIN must be 21 characters, starting with L or U (e.g. U70100MH2015PTC123456)"
        )
    return v


def _rera(v: str) -> str:
    if not re.fullmatch(r"[A-Z0-9/]{6,50}", v):
        raise ValueError("RERA number can use letters, digits and / only (6 to 50 characters)")
    return v


def _account(v: str) -> str:
    if not re.fullmatch(r"[0-9]{9,18}", v):
        raise ValueError("Account number must be 9 to 18 digits")
    return v


GSTIN = Annotated[str, BeforeValidator(_tidy), AfterValidator(_gstin)]
PAN = Annotated[str, BeforeValidator(_tidy), AfterValidator(_pan)]
IFSC = Annotated[str, BeforeValidator(_tidy), AfterValidator(_ifsc)]
CIN = Annotated[str, BeforeValidator(_tidy), AfterValidator(_cin)]
RERA = Annotated[str, BeforeValidator(_tidy), AfterValidator(_rera)]
AccountNumber = Annotated[str, BeforeValidator(_tidy), AfterValidator(_account)]
