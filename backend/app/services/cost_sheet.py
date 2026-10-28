"""Cost sheet, following the developer's PRINT sheet (Habitat):

  Cost of flat        = rate per sq ft x chargeable area (saleable/built-up, else carpet)
  GST                 = cost x GST % (shown per payment stage too)
  Payment stages      = cost x stage %, each with its GST
  Furnishing          = chargeable area x furnishing rate per sq ft
  Stamp duty          = cost x stamp duty %, rounded UP to the next Rs 100
  Registration fees   = cost x registration %, capped (Rs 30,000)
  Legal charges       = fixed amount
  Grand total         = cost + GST + furnishing + stamp duty + registration + legal + other charges

The project holds the template; a unit may override any number (rate, area, charges, percentages).
All money is whole rupees, rounded half up.
"""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel

DEFAULT_TEMPLATE: dict[str, Any] = {
    "developer_name": "",
    "site_address": "",
    "rera_number": "",
    "gst_pct": 1.0,
    "stamp_duty_pct": 7.0,
    "registration_pct": 1.0,
    "registration_cap": 30000,
    "legal_charges": 10000,
    "furnishing_per_sqft": 0.0,
    "stages": [{"name": "Booking", "pct": 10}, {"name": "On agreement", "pct": 90}],
    "notes": [],
    "signatory": "",
}
# Numbers a unit may override
UNIT_OVERRIDES = (
    "gst_pct",
    "stamp_duty_pct",
    "registration_pct",
    "registration_cap",
    "legal_charges",
    "furnishing_per_sqft",
    "chargeable_sqft",
    "other_charges",
    "other_charges_label",
)


def rupees(x: float | Decimal) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class Stage(BaseModel):
    name: str
    pct: float
    amount: int
    gst: int


class CostSheet(BaseModel):
    ready: bool  # False when the unit has no rate/price or no area yet
    missing: list[str]
    project: str
    developer_name: str
    site_address: str
    rera_number: str
    unit_no: str
    unit_label: str  # "A Wing / Floor 2 / Unit 201 / Studio"
    carpet_sqft: float | None
    chargeable_sqft: float | None
    rate_psf: float | None
    cost: int
    gst_pct: float
    gst: int
    stages: list[Stage]
    furnishing_per_sqft: float
    furnishing: int
    stamp_duty_pct: float
    stamp_duty: int
    registration_pct: float
    registration_cap: int
    registration: int
    legal_charges: int
    other_charges_label: str
    other_charges: int
    fees_total: int  # stamp duty + registration + legal
    grand_total: int
    notes: list[str]
    signatory: str
    overrides: dict[str, Any]  # what this unit changes from the project template
    customer: dict[str, Any] | None = None


def merged(template: dict | None, overrides: dict | None) -> dict:
    t = {**DEFAULT_TEMPLATE, **(template or {})}
    for k, v in (overrides or {}).items():
        if k in UNIT_OVERRIDES and v is not None:
            t[k] = v
    return t


def compute(
    *,
    project_name: str,
    template: dict | None,
    overrides: dict | None,
    unit_no: str,
    unit_label: str,
    carpet_sqft: float | None,
    builtup_sqft: float | None,
    rate_psf: float | None,
    asking_price: int | None,
    customer: dict | None = None,
) -> CostSheet:
    t = merged(template, overrides)
    area = t.get("chargeable_sqft") or builtup_sqft or carpet_sqft
    area = float(area) if area else None
    missing = []
    if rate_psf:
        cost = rupees(Decimal(str(rate_psf)) * Decimal(str(area))) if area else 0
    else:
        cost = int(asking_price or 0)
        rate_psf = round(cost / area, 2) if cost and area else None
    if not area:
        missing.append("area")
    if not cost:
        missing.append("price")

    gst_pct = float(t["gst_pct"])
    stages, stage_total = [], 0
    for st in t["stages"]:
        amount = rupees(Decimal(cost) * Decimal(str(st["pct"])) / 100)
        stages.append(
            Stage(
                name=st["name"],
                pct=float(st["pct"]),
                amount=amount,
                gst=rupees(Decimal(amount) * Decimal(str(gst_pct)) / 100),
            )
        )
        stage_total += amount
    gst = rupees(Decimal(cost) * Decimal(str(gst_pct)) / 100)
    # Rounding each stage can leave the columns a few rupees off; the last stage absorbs it,
    # so the stage amounts always add up to the cost and their GST to the GST on cost.
    if stages:
        last = stages[-1]
        last.amount += cost - sum(st.amount for st in stages)
        last.gst += gst - sum(st.gst for st in stages)
    furnishing = rupees(Decimal(str(area or 0)) * Decimal(str(t["furnishing_per_sqft"])))
    stamp = int(math.ceil(cost * float(t["stamp_duty_pct"]) / 100 / 100) * 100) if cost else 0
    registration = min(
        rupees(Decimal(cost) * Decimal(str(t["registration_pct"])) / 100),
        int(t["registration_cap"]),
    )
    legal = int(t["legal_charges"])
    other = int(t.get("other_charges") or 0)
    fees = stamp + registration + legal
    return CostSheet(
        ready=not missing,
        missing=missing,
        project=project_name,
        developer_name=t["developer_name"] or "",
        site_address=t["site_address"] or "",
        rera_number=t["rera_number"] or "",
        unit_no=unit_no,
        unit_label=unit_label,
        carpet_sqft=float(carpet_sqft) if carpet_sqft else None,
        chargeable_sqft=area,
        rate_psf=float(rate_psf) if rate_psf else None,
        cost=cost,
        gst_pct=gst_pct,
        gst=gst,
        stages=stages,
        furnishing_per_sqft=float(t["furnishing_per_sqft"]),
        furnishing=furnishing,
        stamp_duty_pct=float(t["stamp_duty_pct"]),
        stamp_duty=stamp,
        registration_pct=float(t["registration_pct"]),
        registration_cap=int(t["registration_cap"]),
        registration=registration,
        legal_charges=legal,
        other_charges_label=t.get("other_charges_label") or "Other charges",
        other_charges=other,
        fees_total=fees,
        grand_total=cost + gst + furnishing + fees + other,
        notes=list(t["notes"]),
        signatory=t.get("signatory") or "",
        overrides={
            k: v for k, v in (overrides or {}).items() if k in UNIT_OVERRIDES and v is not None
        },
        customer=customer,
    )
