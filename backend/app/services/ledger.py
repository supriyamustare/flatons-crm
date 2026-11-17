"""Ledger rules and the seven balances.

Balances (all whole rupees; "received" = receipts confirmed so far; until the receipts module, the booking amount
recorded on the booking counts as received from the customer's own funds):

  total_payable            = all charges (agreement value + GST + statutory + other)
  total_outstanding        = total_payable - received
  currently_demanded       = max(0, schedule amounts (incl. GST) already due - received)
  overdue                  = max(0, schedule amounts (incl. GST) whose due date has passed - received)
  own_contribution_required= max(0, (total_payable - loan_sanctioned) - received from own funds)
  loan_not_disbursed       = loan_sanctioned - loan disbursed
  under_dispute            = disputed amounts (0 until disputes exist)
  other_charges            = statutory + other charges not yet paid (outside the payment plan)

A schedule item is "due" when its trigger has happened: on booking, or its due date has arrived
(milestone items get a due date when the milestone is verified, in a later sprint)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.models.ledger import (
    AGREEMENT_HEADS,
    OTHER_HEADS,
    STATUTORY_HEADS,
    ChargeHead,
    Ledger,
    ScheduleItem,
    TriggerType,
)


class LedgerRuleError(ValueError):
    pass


HEAD_LABELS = {
    ChargeHead.base_price: "Base price (agreed)",
    ChargeHead.floor_rise: "Floor rise",
    ChargeHead.plc: "Preferred location charge",
    ChargeHead.parking: "Parking",
    ChargeHead.amenities: "Amenities / club house",
    ChargeHead.discount: "Discount",
    ChargeHead.gst: "GST",
    ChargeHead.stamp_duty: "Stamp duty",
    ChargeHead.registration: "Registration fees",
    ChargeHead.legal: "Legal charges",
    ChargeHead.furnishing: "Furnishing",
    ChargeHead.maintenance_deposit: "Maintenance deposit",
    ChargeHead.society_formation: "Society formation",
    ChargeHead.other: "Other charges",
}


def rupees(x) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class Totals(BaseModel):
    agreement_value: int
    gst: int
    statutory: int
    other: int
    total_payable: int
    schedule_amount: int
    schedule_gst: int


class Balances(BaseModel):
    received: int
    received_own: int
    loan_disbursed: int
    total_outstanding: int
    currently_demanded: int
    overdue: int
    own_contribution_required: int
    loan_not_disbursed: int
    under_dispute: int
    other_charges: int


def totals(ledger: Ledger) -> Totals:
    by = lambda heads: sum(c.amount for c in ledger.charges if c.head in heads)  # noqa: E731
    agreement, gst = by(AGREEMENT_HEADS), by((ChargeHead.gst,))
    statutory, other = by(STATUTORY_HEADS), by(OTHER_HEADS)
    return Totals(
        agreement_value=agreement,
        gst=gst,
        statutory=statutory,
        other=other,
        total_payable=agreement + gst + statutory + other,
        schedule_amount=sum(i.amount for i in ledger.schedule),
        schedule_gst=sum(i.gst for i in ledger.schedule),
    )


def is_due(item: ScheduleItem, today: date) -> bool:
    return item.due_date is not None and item.due_date <= today


def balances(
    ledger: Ledger, *, received_own: int, loan_disbursed: int = 0, disputed: int = 0, today: date
) -> Balances:
    t = totals(ledger)
    received = received_own + loan_disbursed
    due = sum(i.amount + i.gst for i in ledger.schedule if is_due(i, today))
    past = sum(
        i.amount + i.gst for i in ledger.schedule if i.due_date is not None and i.due_date < today
    )
    return Balances(
        received=received,
        received_own=received_own,
        loan_disbursed=loan_disbursed,
        total_outstanding=t.total_payable - received,
        currently_demanded=max(0, due - received),
        overdue=max(0, past - received),
        own_contribution_required=max(0, t.total_payable - ledger.loan_sanctioned - received_own),
        loan_not_disbursed=max(0, ledger.loan_sanctioned - loan_disbursed),
        under_dispute=disputed,
        other_charges=t.statutory + t.other,
    )


def split_gst(amounts: list[int], gst_pct: float, total_gst: int | None = None) -> list[int]:
    """GST per stage; the last stage absorbs rounding so the column adds up to the GST charge."""
    each = [rupees(Decimal(a) * Decimal(str(gst_pct)) / 100) for a in amounts]
    if each and total_gst is not None:
        each[-1] += total_gst - sum(each)
    return each


def problems(ledger: Ledger) -> list[str]:
    """What must be right before the ledger can be submitted or approved."""
    t = totals(ledger)
    out = []
    if not any(c.head == ChargeHead.base_price for c in ledger.charges):
        out.append("A base price charge is required")
    if not ledger.schedule:
        out.append("The payment schedule is empty")
    if t.schedule_amount != t.agreement_value:
        out.append(
            f"Payment schedule adds up to Rs {t.schedule_amount:,}; it must equal the agreement value Rs {t.agreement_value:,}"
        )
    expected_gst = rupees(Decimal(t.agreement_value) * Decimal(str(ledger.gst_pct)) / 100)
    if t.gst != expected_gst:
        out.append(
            f"GST charge is Rs {t.gst:,}; at {float(ledger.gst_pct):g}% of the agreement value it should be Rs {expected_gst:,}"
        )
    if t.schedule_gst != t.gst:
        out.append(
            f"GST across the schedule is Rs {t.schedule_gst:,}; it must equal the GST charge Rs {t.gst:,}"
        )
    if ledger.loan_sanctioned > t.total_payable:
        out.append("The loan can't be more than the total payable")
    if ledger.loan_sanctioned and not ledger.lender:
        out.append("Name the lender for the loan")
    for i in ledger.schedule:
        if i.trigger_type == TriggerType.on_milestone and not i.milestone:
            out.append(f"Stage {i.name}: name its milestone")
    return out
