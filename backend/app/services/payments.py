"""Matching receipts to the ledger and working out what's paid.

Only confirmed receipts count as paid. Recorded (unconfirmed) receipts still reserve their matched amounts, so two
receipts can't both be matched to the same rupees of a stage."""

from collections import defaultdict

from app.models.ledger import OTHER_HEADS, STATUTORY_HEADS, ChargeHead, Ledger
from app.models.payment import LIVE, FundSource, Receipt, ReceiptStatus

PAYABLE_HEADS = (
    *STATUTORY_HEADS,
    *OTHER_HEADS,
)  # charges outside the payment plan that receipts can be matched to


class MatchError(ValueError):
    pass


def position(ledger: Ledger, receipts: list[Receipt]) -> dict:
    confirmed = [r for r in receipts if r.status == ReceiptStatus.confirmed]
    paid_stage: dict[int, int] = defaultdict(int)
    paid_head: dict[ChargeHead, int] = defaultdict(int)
    for r in confirmed:
        for a in r.allocations:
            if a.stage_seq is not None:
                paid_stage[a.stage_seq] += a.amount
            else:
                paid_head[a.charge_head] += a.amount
    return {
        "paid_by_stage": dict(paid_stage),
        "paid_by_head": dict(paid_head),
        "paid_other": sum(paid_head.values()),
        "received_own": sum(r.amount for r in confirmed if r.source == FundSource.own),
        "loan_disbursed": sum(r.amount for r in confirmed if r.source == FundSource.loan),
        "pending": sum(r.amount for r in receipts if r.status == ReceiptStatus.recorded),
    }


def reserved(
    receipts: list[Receipt], exclude_id: int | None = None
) -> tuple[dict[int, int], dict[ChargeHead, int]]:
    """Amounts already matched by live (recorded or confirmed) receipts, per stage and per charge head."""
    stage, head = defaultdict(int), defaultdict(int)
    for r in receipts:
        if r.status in LIVE and r.id != exclude_id:
            for a in r.allocations:
                if a.stage_seq is not None:
                    stage[a.stage_seq] += a.amount
                else:
                    head[a.charge_head] += a.amount
    return stage, head


def head_totals(ledger: Ledger) -> dict[ChargeHead, int]:
    out: dict[ChargeHead, int] = defaultdict(int)
    for c in ledger.charges:
        if c.head in PAYABLE_HEADS:
            out[c.head] += c.amount
    return out


def auto_match(
    ledger: Ledger, receipts: list[Receipt], amount: int, exclude_id: int | None = None
) -> list[tuple[int, int]]:
    """Oldest unpaid stages first. Returns (stage number, amount); anything left over stays unapplied (an advance)."""
    taken, _ = reserved(receipts, exclude_id)
    out, left = [], amount
    for item in sorted(ledger.schedule, key=lambda i: i.seq):
        room = item.amount + item.gst - taken.get(item.seq, 0)
        if left <= 0:
            break
        if room > 0:
            use = min(room, left)
            out.append((item.seq, use))
            left -= use
    return out


def check_match(
    ledger: Ledger,
    receipts: list[Receipt],
    receipt_amount: int,
    stages: list[tuple[int, int]],
    heads: list[tuple[ChargeHead, int]],
    exclude_id: int | None = None,
) -> None:
    if sum(a for _, a in stages) + sum(a for _, a in heads) > receipt_amount:
        raise MatchError("You've matched more than the receipt's amount")
    taken_stage, taken_head = reserved(receipts, exclude_id)
    by_seq = {i.seq: i for i in ledger.schedule}
    totals = head_totals(ledger)
    seen_s, seen_h = defaultdict(int), defaultdict(int)
    for seq, amt in stages:
        seen_s[seq] += amt
    for h, amt in heads:
        seen_h[h] += amt
    for seq, amt in seen_s.items():
        item = by_seq.get(seq)
        if item is None:
            raise MatchError(f"There's no stage {seq} in the payment schedule")
        room = item.amount + item.gst - taken_stage.get(seq, 0)
        if amt > room:
            raise MatchError(f"{item.name}: only Rs {max(room, 0):,} is still unpaid")
    for h, amt in seen_h.items():
        if h not in PAYABLE_HEADS:
            raise MatchError("Receipts can be matched to stages, or to statutory and other charges")
        room = totals.get(h, 0) - taken_head.get(h, 0)
        if amt > room:
            raise MatchError(
                f"{h.value.replace('_', ' ').capitalize()}: only Rs {max(room, 0):,} is still unpaid"
            )


def schedule_fits(new_items: list[tuple[int, str, int]], receipts: list[Receipt]) -> None:
    """A changed schedule must still cover what live receipts are matched to (by stage number)."""
    taken, _ = reserved(receipts)
    by_seq = {seq: (name, total) for seq, name, total in new_items}
    for seq, amt in taken.items():
        name, total = by_seq.get(seq, (f"stage {seq}", 0))
        if amt > total:
            raise MatchError(
                f"Receipts of Rs {amt:,} are matched to {name}; it can't be less than that"
            )


def charges_fit(new_totals: dict[ChargeHead, int], receipts: list[Receipt]) -> None:
    _, taken = reserved(receipts)
    for h, amt in taken.items():
        if amt > new_totals.get(h, 0):
            raise MatchError(
                f"Receipts of Rs {amt:,} are matched to {h.value.replace('_', ' ')}; it can't be less than that"
            )
