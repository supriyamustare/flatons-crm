"""Agreement conditions, data checks (discrepancies) and the draft built from the approved template."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Building, Floor, Unit
from app.models.ledger import AGREEMENT_HEADS, ChargeHead, Ledger, LedgerStatus
from app.models.payment import Receipt, ReceiptStatus
from app.models.postsales import CoApplicant, CustomerProfile, OnboardingStatus, PostSalesCase
from app.models.project import Project
from app.models.project_legal import ProjectLegal
from app.services import doc_readiness
from app.services import ledger as ledger_svc
from app.services import postsales as cases
from app.services.cost_sheet import merged

# Placeholder clauses: Legal must replace these with the developer's approved wording (Cost sheet settings > Agreement).
DEFAULT_CLAUSES = [
    "[PLACEHOLDER: replace with the approved clause] The Developer agrees to sell and the Purchaser(s) agree to purchase Unit {unit_no} "
    "in {project} for a total consideration of Rs {agreement_value}, as described in this agreement.",
    "[PLACEHOLDER] The consideration shall be paid in accordance with the payment schedule annexed to this agreement.",
    "[PLACEHOLDER] Possession, defect liability, cancellation, interest on delayed payment and dispute resolution clauses as approved by Legal.",
]


def settings(project: Project) -> dict:
    t = merged(project.cost_sheet, None)
    return {
        "min_paid_pct": float(t.get("agreement_min_paid_pct", 10)),
        "requires_kyc": bool(t.get("agreement_requires_kyc", True)),
        "clauses": list(t.get("agreement_clauses") or DEFAULT_CLAUSES),
    }


async def _parts(db: AsyncSession, case: PostSalesCase):
    project = await db.get(Project, case.booking.project_id)
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    receipts = list(
        await db.scalars(
            select(Receipt).where(
                Receipt.case_id == case.id, Receipt.status == ReceiptStatus.confirmed
            )
        )
    )
    profile = await db.get(CustomerProfile, case.id)
    co = list(
        await db.scalars(
            select(CoApplicant)
            .where(CoApplicant.case_id == case.id)
            .order_by(CoApplicant.sort_order, CoApplicant.id)
        )
    )
    return project, ledger, receipts, profile, co


async def conditions(db: AsyncSession, case: PostSalesCase) -> list[dict]:
    """The trigger for starting an agreement (configured per project, not hard-coded)."""
    project, ledger, receipts, _, _ = await _parts(db, case)
    cfg = settings(project)
    agreement_value = ledger_svc.totals(ledger).agreement_value if ledger else 0
    paid = sum(r.amount for r in receipts)
    need = int(Decimal(agreement_value) * Decimal(str(cfg["min_paid_pct"])) / 100)
    out = [
        {
            "item": "Ledger approved",
            "ok": ledger is not None and ledger.status == LedgerStatus.approved,
        },
        {
            "item": f"At least {cfg['min_paid_pct']:g}% of the agreement value received (Rs {need:,})",
            "ok": ledger is not None and paid >= need,
            "detail": f"Received Rs {paid:,}",
        },
    ]
    if cfg["requires_kyc"]:
        out.insert(
            0, {"item": "KYC approved", "ok": case.onboarding_status == OnboardingStatus.approved}
        )
    return out


async def checks(db: AsyncSession, case: PostSalesCase) -> list[dict]:
    """Data verification: names, ownership, unit, consideration, schedule and tax must agree everywhere."""
    project, ledger, _, profile, co = await _parts(db, case)
    unit = await db.get(Unit, case.booking.unit_id)
    legal = await db.get(ProjectLegal, project.id)
    readiness = await doc_readiness.check(db, project)
    base = sum(c.amount for c in ledger.charges if c.head == ChargeHead.base_price) if ledger else 0
    problems = cases.profile_problems(profile, co) if profile else ["Customer details"]
    out = [
        {
            "item": "Purchaser's legal name and PAN",
            "ok": bool(profile and profile.legal_name and profile.pan),
        },
        {
            "item": "Ownership structure complete",
            "ok": not [
                p for p in problems if "Ownership" in p or "co-applicant" in p or "Entity" in p
            ],
            "detail": "; ".join(
                p for p in problems if "Ownership" in p or "co-applicant" in p or "Entity" in p
            )
            or None,
        },
        {"item": "Co-applicants have PANs", "ok": all(c.pan for c in co)},
        {
            "item": "Unit areas recorded",
            "ok": bool(unit and unit.carpet_sqft and unit.builtup_sqft),
        },
        {
            "item": "Booking price matches the ledger's base price",
            "ok": bool(ledger) and base == case.booking.agreed_price,
            "detail": f"Booking Rs {case.booking.agreed_price:,}; ledger base price Rs {base:,}"
            if ledger and base != case.booking.agreed_price
            else None,
        },
        {
            "item": "Payment schedule matches the agreement value and GST",
            "ok": bool(ledger) and not ledger_svc.problems(ledger),
            "detail": "; ".join(ledger_svc.problems(ledger))
            if ledger and ledger_svc.problems(ledger)
            else None,
        },
        {
            "item": "Developer's legal details complete",
            "ok": not readiness.legal_missing and bool(legal),
            "detail": ", ".join(readiness.legal_missing) or None,
        },
    ]

    return out


def inr(n: int) -> str:
    """Indian digit grouping: 3225000 -> 32,25,000."""
    s, sign = str(abs(int(n))), "-" if n < 0 else ""
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return (
        sign + ",".join([head, *groups]) + "," + tail
        if head
        else sign + ",".join(groups) + "," + tail
    )


def _fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


async def build_draft(
    db: AsyncSession, case: PostSalesCase, agreement_no: str, version: int, today: date
) -> dict:
    project, ledger, _, profile, co = await _parts(db, case)
    unit = await db.get(Unit, case.booking.unit_id)
    building = await db.get(Building, unit.building_id) if unit and unit.building_id else None
    floor = await db.get(Floor, unit.floor_id) if unit and unit.floor_id else None
    legal = await db.get(ProjectLegal, project.id)
    t = ledger_svc.totals(ledger)
    values = {
        "project": project.name,
        "unit_no": unit.unit_no,
        "agreement_value": inr(t.agreement_value),
        "agreement_no": agreement_no,
    }
    purchasers = [
        {
            "name": profile.legal_name,
            "pan": profile.pan,
            "share": float(profile.ownership_pct) if profile.ownership_pct else None,
            "address": profile.correspondence_address,
            "entity": profile.entity_name,
            "ownership": profile.ownership_type.value,
        }
    ]
    purchasers += [
        {
            "name": c.name,
            "pan": c.pan,
            "share": float(c.ownership_pct) if c.ownership_pct else None,
            "relation": c.relation,
        }
        for c in co
    ]
    return {
        "agreement_no": agreement_no,
        "version": version,
        "date": today.isoformat(),
        "developer": {
            "name": legal.developer_legal_name,
            "address": legal.registered_address,
            "gstin": legal.gstin,
            "cin": legal.cin,
            "signatory": legal.signatory_name,
            "designation": legal.signatory_designation,
            "rera": legal.rera_number,
        },
        "purchasers": purchasers,
        "unit": {
            "project": project.name,
            "location": project.location,
            "building": building.name if building else None,
            "floor": floor.number if floor else None,
            "unit_no": unit.unit_no,
            "type": unit.unit_type.value,
            "carpet_sqft": float(unit.carpet_sqft) if unit.carpet_sqft else None,
            "saleable_sqft": float(unit.builtup_sqft) if unit.builtup_sqft else None,
        },
        "consideration": [
            {"label": c.label, "amount": c.amount}
            for c in ledger.charges
            if c.head in AGREEMENT_HEADS
        ],
        "agreement_value": t.agreement_value,
        "gst": t.gst,
        "gst_pct": float(ledger.gst_pct),
        "schedule": [
            {
                "name": i.name,
                "amount": i.amount,
                "gst": i.gst,
                "due": "On booking"
                if i.trigger_type.value == "on_booking"
                else (
                    i.due_date.isoformat()
                    if i.trigger_type.value == "on_date"
                    else f"On {i.milestone}"
                ),
            }
            for i in sorted(ledger.schedule, key=lambda x: x.seq)
        ],
        "clauses": [_fill(c, values) for c in settings(project)["clauses"]],
        "placeholder_clauses": any("[PLACEHOLDER" in c for c in settings(project)["clauses"]),
    }
