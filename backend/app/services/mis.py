"""Management dashboard and MIS reports (Section 6).

Everything is worked out with the same functions the case tabs use (balances, payments, KYC requirements, promise status),
so a report and the case it comes from always agree. "Current" figures are live; period figures use a from-to range;
historical positions come from the nightly snapshots (mis_snapshots).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models.aftersales import Defect
from app.models.agreement import Agreement, AgreementStatus
from app.models.booking import Booking
from app.models.cancellation import Cancellation
from app.models.case_document import Approval, CaseDocument
from app.models.demand import Demand, DemandStatus
from app.models.followup import PaymentFollowUp
from app.models.inventory import Unit
from app.models.ledger import Ledger, LedgerStatus
from app.models.loan import Disbursement, DisbursementStatus, Loan
from app.models.payment import Receipt, ReceiptStatus
from app.models.possession import PossessionFile, Snag
from app.models.postsales import (
    CaseStatus,
    CoApplicant,
    CustomerProfile,
    KycDocument,
    PostSalesCase,
)
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User
from app.services import ledger as ledger_svc
from app.services import payments
from app.services import postsales as case_svc
from app.services import tickets as ticket_svc
from app.services.followups import promise_status

IST = timezone(timedelta(hours=5, minutes=30))
BUCKETS = (("1-30", 1, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("90+", 91, 10**6))
NOT_AVAILABLE = {
    "unmatched_bank_transactions": "Needs bank-statement import, which isn't built yet.",
    "waivers": "There's no waiver approval process yet; cancellation deductions are listed under adjustments.",
    "tax_tds": "TDS isn't captured on receipts yet, so it can't be reconciled.",
}


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


@dataclass
class Filters:
    project_id: int | None = None
    building_id: int | None = None
    owner_id: int | None = None
    booking_from: date | None = None
    booking_to: date | None = None
    period_from: date | None = None
    period_to: date | None = None

    def in_period(self, d: date | None) -> bool:
        if d is None:
            return False
        return (self.period_from is None or d >= self.period_from) and (
            self.period_to is None or d <= self.period_to
        )


async def _cases(db, f: Filters, statuses=(CaseStatus.accepted,)) -> list[PostSalesCase]:
    q = (
        select(PostSalesCase)
        .join(Booking, Booking.id == PostSalesCase.booking_id)
        .where(PostSalesCase.status.in_(list(statuses)))
    )
    if f.project_id:
        q = q.where(Booking.project_id == f.project_id)
    if f.owner_id:
        q = q.where(PostSalesCase.owner_id == f.owner_id)
    if f.booking_from:
        q = q.where(Booking.booking_date >= f.booking_from)
    if f.booking_to:
        q = q.where(Booking.booking_date <= f.booking_to)
    if f.building_id:
        q = q.join(Unit, Unit.id == Booking.unit_id).where(Unit.building_id == f.building_id)
    return list(await db.scalars(q.order_by(PostSalesCase.id)))


def _row(case: PostSalesCase) -> dict:
    b = case.booking
    return {
        "case_id": case.id,
        "case_code": case_svc.code(case),
        "customer": b.customer_name or b.lead.name,
        "project": b.project.name,
        "unit": b.unit.unit_no,
        "owner": case.owner.full_name if case.owner else None,
    }


async def money(db, f: Filters) -> list[dict]:
    """Per case: the ledger position, stage by stage, with ageing."""
    t = today()
    out = []
    for case in await _cases(db, f):
        ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
        receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == case.id)))
        if ledger is None:
            out.append({**_row(case), "has_ledger": False, "receipts": receipts})
            continue
        pos = payments.position(ledger, receipts)
        bal = ledger_svc.balances(
            ledger,
            received_own=pos["received_own"],
            loan_disbursed=pos["loan_disbursed"],
            today=t,
            paid_by_stage=pos["paid_by_stage"],
            paid_other=pos["paid_other"],
            pending=pos["pending"],
        )
        paid = pos["paid_by_stage"]
        stages, ageing, due_total, due_paid = [], dict.fromkeys([b[0] for b in BUCKETS], 0), 0, 0
        not_yet_due = 0
        for i in ledger.schedule:
            total = i.amount + i.gst
            got = paid.get(i.seq, 0)
            left = max(0, total - got)
            due = ledger_svc.is_due(i, t)
            stages.append(
                {
                    "name": i.name,
                    "amount": total,
                    "paid": got,
                    "outstanding": left,
                    "demanded_on": i.demanded_on,
                    "due_date": i.due_date,
                    "due": due,
                }
            )
            if not due:
                continue
            if i.due_date and i.due_date > t:  # due after today: demanded, not yet due
                not_yet_due += left
                continue
            due_total += total
            due_paid += min(total, got)
            days = (t - i.due_date).days if i.due_date else 0
            for name, lo, hi in BUCKETS:
                if lo <= days <= hi and left:
                    ageing[name] += left
        out.append(
            {
                **_row(case),
                "has_ledger": True,
                "ledger_approved": ledger.status == LedgerStatus.approved,
                "payable": ledger_svc.totals(ledger).total_payable,
                "received": bal.received,
                "received_own": bal.received_own,
                "loan_disbursed": bal.loan_disbursed,
                "outstanding": bal.total_outstanding,
                "overdue": bal.overdue,
                "demanded_not_due": not_yet_due,
                "own_required": bal.own_contribution_required,
                "unapplied": bal.unapplied,
                "pending_confirmation": bal.pending_confirmation,
                "due_total": due_total,
                "due_paid": due_paid,
                "ageing": ageing,
                "stages": stages,
                "receipts": receipts,
                "project_id": case.booking.project_id,
            }
        )
    return out


def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


async def finance(db, f: Filters) -> dict:
    t = today()
    rows = await money(db, f)
    live = [r for r in rows if r["has_ledger"]]
    by_project: dict = defaultdict(
        lambda: {
            "cases": 0,
            "consideration": 0,
            "demanded": 0,
            "collected": 0,
            "awaiting_confirmation": 0,
            "due_total": 0,
            "due_paid": 0,
        }
    )
    for r in live:
        p = by_project[r["project"]]
        p["cases"] += 1
        p["consideration"] += r["payable"]
        p["due_total"] += r["due_total"]
        p["due_paid"] += r["due_paid"]
        p["demanded"] += sum(
            s["amount"]
            for s in r["stages"]
            if s["demanded_on"]
            and (f.period_from is None and f.period_to is None or f.in_period(s["demanded_on"]))
        )
        for rc in r["receipts"]:
            if rc.status == ReceiptStatus.confirmed and (
                f.period_from is None and f.period_to is None or f.in_period(rc.received_on)
            ):
                p["collected"] += rc.amount
            if rc.status == ReceiptStatus.recorded:
                p["awaiting_confirmation"] += rc.amount
    projects = [
        {"project": k, **v, "collection_efficiency_pct": _pct(v["due_paid"], v["due_total"])}
        for k, v in sorted(by_project.items())
    ]
    upcoming = {}
    for n in (7, 15, 30):
        items = [
            {
                **{
                    k: r[k]
                    for k in ("case_id", "case_code", "customer", "project", "unit", "owner")
                },
                "stage": s["name"],
                "due_date": s["due_date"],
                "amount": s["outstanding"],
            }
            for r in live
            for s in r["stages"]
            if s["due"]
            and s["due_date"]
            and t < s["due_date"] <= t + timedelta(days=n)
            and s["outstanding"]
        ]
        upcoming[str(n)] = {
            "count": len(items),
            "amount": sum(i["amount"] for i in items),
            "items": sorted(items, key=lambda i: i["due_date"]),
        }
    ageing_total = dict.fromkeys([b[0] for b in BUCKETS], 0)
    for r in live:
        for k, v in r["ageing"].items():
            ageing_total[k] += v
    case_ids = [r["case_id"] for r in rows]
    loans = (
        list(
            await db.scalars(
                select(Loan).where(Loan.case_id.in_(case_ids), Loan.closed_at.is_(None))
            )
        )
        if case_ids
        else []
    )
    disb = []
    for ln in loans:
        received = sum(
            d.actual_amount or 0
            for d in ln.disbursements
            if d.status == DisbursementStatus.received
        )
        open_reqs = [
            d
            for d in ln.disbursements
            if d.status in (DisbursementStatus.requested, DisbursementStatus.awaited)
        ]
        r = next(x for x in rows if x["case_id"] == ln.case_id)
        if (ln.sanctioned_amount or 0) - received > 0 or open_reqs:
            disb.append(
                {
                    **{
                        k: r[k]
                        for k in ("case_id", "case_code", "customer", "project", "unit", "owner")
                    },
                    "lender": ln.lender,
                    "sanctioned": ln.sanctioned_amount or 0,
                    "disbursed": received,
                    "not_disbursed": max(0, (ln.sanctioned_amount or 0) - received),
                    "open_requests": sum(d.expected_amount for d in open_reqs),
                    "oldest_request": min((d.request_date for d in open_reqs), default=None),
                }
            )
    all_receipts = [(r, rc) for r in rows for rc in r["receipts"]]
    failed = [
        {
            **{k: r[k] for k in ("case_id", "case_code", "customer", "project", "unit")},
            "receipt": f"RCT-{rc.id:05d}",
            "amount": rc.amount,
            "mode": rc.mode.value,
            "status": rc.status.value,
            "reason": rc.void_reason,
            "date": rc.received_on,
        }
        for r, rc in all_receipts
        if rc.status in (ReceiptStatus.bounced, ReceiptStatus.reversed)
        and (f.period_from is None and f.period_to is None or f.in_period(rc.received_on))
    ]
    cancels = (
        list(
            await db.scalars(
                select(Cancellation).where(
                    Cancellation.case_id.in_(
                        case_ids + [r.id for r in await _cases(db, f, (CaseStatus.cancelled,))]
                    )
                )
            )
        )
        if case_ids or True
        else []
    )
    refunds, adjustments = [], []
    for c in cancels:
        st = c.settlement or {}
        if c.status in ("withdrawn", "rejected"):
            continue
        case = await db.get(PostSalesCase, c.case_id)
        base = {**_row(case), "cancellation": f"CXL-{c.id:05d}", "status": c.status}
        if st.get("refund", 0) > 0 and not (c.refund_payment or {}).get("reconciled_by"):
            refunds.append(
                {
                    **base,
                    "refund": st["refund"],
                    "stage": "awaiting approval"
                    if c.status == "settlement_proposed"
                    else "awaiting payment"
                    if not c.refund_payment
                    else "awaiting reconciliation",
                }
            )
        for d in st.get("deductions", []):
            adjustments.append(
                {
                    **base,
                    "kind": "Cancellation deduction",
                    "label": d["label"],
                    "amount": d["amount"],
                    "basis": d["basis"],
                }
            )
    customers = [
        {
            **{k: r[k] for k in ("case_id", "case_code", "customer", "project", "unit", "owner")},
            **{
                k: r[k]
                for k in (
                    "payable",
                    "received",
                    "outstanding",
                    "overdue",
                    "demanded_not_due",
                    "own_required",
                    "unapplied",
                    "pending_confirmation",
                )
            },
        }
        for r in live
    ]
    return {
        "projects": projects,
        "totals": {
            "consideration": sum(p["consideration"] for p in projects),
            "demanded": sum(p["demanded"] for p in projects),
            "collected": sum(p["collected"] for p in projects),
            "awaiting_confirmation": sum(p["awaiting_confirmation"] for p in projects),
            "collection_efficiency_pct": _pct(
                sum(p["due_paid"] for p in projects), sum(p["due_total"] for p in projects)
            ),
            "overdue": sum(r["overdue"] for r in live),
            "outstanding": sum(r["outstanding"] for r in live),
        },
        "own_contribution": {
            "required": sum(r["own_required"] for r in live),
            "received": sum(r["received_own"] for r in live),
            "items": [c for c in customers if c["own_required"] > 0],
        },
        "upcoming": upcoming,
        "ageing": ageing_total,
        "ageing_items": sorted(
            [
                {
                    **{
                        k: r[k]
                        for k in ("case_id", "case_code", "customer", "project", "unit", "owner")
                    },
                    **r["ageing"],
                    "overdue": r["overdue"],
                }
                for r in live
                if r["overdue"]
            ],
            key=lambda x: -x["overdue"],
        ),
        "customers": sorted(customers, key=lambda x: -x["outstanding"]),
        "disbursement_pending": disb,
        "unallocated": [c for c in customers if c["unapplied"] > 0],
        "failed_payments": failed,
        "refunds_pending": refunds,
        "adjustments": adjustments,
        "no_ledger": [
            {k: r[k] for k in ("case_id", "case_code", "customer", "project", "unit", "owner")}
            for r in rows
            if not r["has_ledger"]
        ],
        "not_available": NOT_AVAILABLE,
    }


def _age(d: datetime | date | None) -> int | None:
    if d is None:
        return None
    d0 = d.astimezone(IST).date() if isinstance(d, datetime) else d
    return (today() - d0).days


async def operations(db, f: Filters) -> dict:
    t = today()
    accepted = await _cases(db, f)
    ids = [c.id for c in accepted]
    pending = await _cases(db, f, (CaseStatus.handover_pending,))
    kyc_incomplete = []
    for c in accepted:
        profile = await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == c.id))
        co = list(await db.scalars(select(CoApplicant).where(CoApplicant.case_id == c.id)))
        docs = list(await db.scalars(select(KycDocument).where(KycDocument.case_id == c.id)))
        reqs = case_svc.requirements(profile, co, docs) if profile else []
        done = sum(1 for r in reqs if r["status"] == "verified")
        if not reqs or done < len(reqs):
            kyc_incomplete.append(
                {**_row(c), "done": done, "total": len(reqs), "profile": profile is not None}
            )
    agreements = (
        {
            a.case_id: a
            for a in await db.scalars(
                select(Agreement).where(
                    Agreement.case_id.in_(ids), Agreement.status != AgreementStatus.cancelled
                )
            )
        }
        if ids
        else {}
    )
    by_stage: dict = defaultdict(int)
    agreement_items = []
    for c in accepted:
        a = agreements.get(c.id)
        st = a.status.value if a else "not_started"
        if st in ("registered", "final_uploaded"):
            continue
        by_stage[st] += 1
        agreement_items.append(
            {
                **_row(c),
                "stage": st,
                "since": a.updated_at if a else c.accepted_at,
                "days": _age(a.updated_at if a else c.accepted_at),
            }
        )
    docs = (
        list(
            await db.scalars(
                select(CaseDocument).where(
                    CaseDocument.case_id.in_(ids),
                    CaseDocument.approval.in_([Approval.under_approval, Approval.approved]),
                )
            )
        )
        if ids
        else []
    )
    by_case = {c.id: c for c in accepted}
    awaiting = [
        {
            **_row(by_case[d.case_id]),
            "document": f"DOC-{d.id:05d}",
            "title": d.title,
            "category": d.category.value,
            "days": _age(d.uploaded_at),
        }
        for d in docs
        if d.approval == Approval.under_approval
    ]
    unreleased = [
        {
            **_row(by_case[d.case_id]),
            "document": f"DOC-{d.id:05d}",
            "title": d.title,
            "category": d.category.value,
            "visibility": d.visibility.value,
            "days": _age(d.uploaded_at),
        }
        for d in docs
        if d.approval == Approval.approved and d.visibility.value == "customer"
    ]
    fus = (
        list(
            await db.scalars(
                select(PaymentFollowUp)
                .where(PaymentFollowUp.case_id.in_(ids))
                .order_by(PaymentFollowUp.id)
            )
        )
        if ids
        else []
    )
    latest: dict = {}
    for fu in fus:
        latest[fu.case_id] = fu
    receipts = defaultdict(list)
    for r in (await db.scalars(select(Receipt).where(Receipt.case_id.in_(ids)))) if ids else []:
        receipts[r.case_id].append(r)
    overdue_fu = [
        {
            **_row(by_case[cid]),
            "due_on": fu.next_follow_up_on,
            "days": (t - fu.next_follow_up_on).days,
        }
        for cid, fu in latest.items()
        if fu.next_follow_up_on and fu.next_follow_up_on < t
    ]
    broken = [
        {
            **_row(by_case[fu.case_id]),
            "promise_date": fu.promise_date,
            "promise_amount": fu.promise_amount,
        }
        for fu in fus
        if fu.promise_date and promise_status(fu, receipts[fu.case_id], t) == "broken"
    ]
    tickets = list(await db.scalars(select(Ticket).where(Ticket.case_id.in_(ids)))) if ids else []
    cfg = await ticket_svc.get_settings(db)
    open_t = [x for x in tickets if x.status != TicketStatus.closed]
    age_b = (("0-2 days", 0, 2), ("3-7 days", 3, 7), ("8-30 days", 8, 30), ("30+ days", 31, 10**6))
    by_team: dict = defaultdict(lambda: defaultdict(int))
    for x in open_t:
        a = _age(x.created_at)
        by_team[ticket_svc.TEAM_LABELS[x.team]][x.priority.value] += 1
        by_team[ticket_svc.TEAM_LABELS[x.team]][
            next(n for n, lo, hi in age_b if lo <= a <= hi)
        ] += 1
        by_team[ticket_svc.TEAM_LABELS[x.team]]["total"] += 1
    breaches = []
    for x in tickets:
        s = ticket_svc.sla(x, None, cfg["at_risk_pct"])
        if s["resolution_breached"] or (s["response_breached"] and not s["first_response_at"]):
            breaches.append(
                {
                    **_row(by_case[x.case_id]),
                    "ticket": f"TKT-{x.id:05d}",
                    "title": x.title,
                    "team": ticket_svc.TEAM_LABELS[x.team],
                    "priority": x.priority.value,
                    "status": x.status.value,
                    "kind": "resolution" if s["resolution_breached"] else "first response",
                    "escalation_level": x.escalation_level,
                }
            )
    requests_waiting = [
        {
            **_row(by_case[x.case_id]),
            "item": f"TKT-{x.id:05d}",
            "what": f"{ticket_svc.LABELS[x.category]}: resolution waiting for the customer",
            "days": _age(x.resolved_at),
        }
        for x in open_t
        if x.status == TicketStatus.resolution_proposed
    ]
    all_cancels = (
        list(
            await db.scalars(
                select(Cancellation).where(Cancellation.status.notin_(["withdrawn", "rejected"]))
            )
        )
        if True
        else []
    )
    for c in all_cancels:
        if c.case_id in by_case and c.status == "settlement_proposed":
            requests_waiting.append(
                {
                    **_row(by_case[c.case_id]),
                    "item": f"CXL-{c.id:05d}",
                    "what": "Cancellation settlement waiting for approval",
                    "days": _age(c.updated_at),
                }
            )
    files = (
        {
            pf.case_id: pf
            for pf in await db.scalars(
                select(PossessionFile).where(PossessionFile.case_id.in_(ids))
            )
        }
        if ids
        else {}
    )
    ready, delays = [], []
    from app.models.project import Project
    from app.services import possession as pos_svc

    for cid, pf in files.items():
        if pf.handover_completed_at:
            continue
        case = by_case[cid]
        project = await db.get(Project, case.booking.project_id)
        g = await pos_svc.gate(db, case, pf, project, pos_svc.project_rules(project))
        if g["open"]:
            ready.append(
                {
                    **_row(case),
                    "eligible_since": pf.gate_opened_at,
                    "days_waiting": _age(pf.gate_opened_at),
                }
            )
        else:
            delays.append(
                {
                    **_row(case),
                    "started": pf.created_at,
                    "days_open": _age(pf.created_at),
                    "pending": [
                        c["label"] for c in g["conditions"] if not (c["met"] or c["excepted"])
                    ],
                }
            )
    snags = (
        list(
            await db.scalars(
                select(Snag)
                .join(PossessionFile, PossessionFile.id == Snag.file_id)
                .where(PossessionFile.case_id.in_(ids), Snag.status != "closed")
            )
        )
        if ids
        else []
    )
    snag_files = {pf.id: pf.case_id for pf in files.values()}
    q = select(Defect).where(Defect.status != "closed")
    if f.project_id:
        q = q.where(Defect.project_id == f.project_id)
    defects = [
        d
        for d in await db.scalars(q)
        if d.case_id is None
        and not (f.owner_id or f.building_id or f.booking_from or f.booking_to)
        or d.case_id in by_case
    ]
    open_items = [
        {
            **_row(by_case[snag_files[s.file_id]]),
            "kind": "Snag",
            "ref": f"SNG-{s.id:05d}",
            "category": s.category,
            "severity": s.severity,
            "status": s.status,
            "due": s.due_on,
            "overdue": bool(s.due_on and s.due_on < t),
        }
        for s in snags
    ]
    for d in defects:
        base = (
            _row(by_case[d.case_id])
            if d.case_id
            else {
                "case_id": None,
                "case_code": None,
                "customer": "Common area",
                "project": None,
                "unit": None,
                "owner": None,
            }
        )
        open_items.append(
            {
                **base,
                "kind": "Defect",
                "ref": f"DEF-{d.id:05d}",
                "category": d.category,
                "severity": None,
                "status": d.status,
                "due": d.target_date,
                "overdue": bool(d.target_date and d.target_date < t),
            }
        )
    cancels_rows = []
    for c in all_cancels:
        case = await db.get(PostSalesCase, c.case_id)
        if f.project_id and case.booking.project_id != f.project_id:
            continue
        cancels_rows.append(
            {
                **_row(case),
                "cancellation": f"CXL-{c.id:05d}",
                "status": c.status,
                "reason": c.reason_code,
                "requested": c.request_date,
                "refund": (c.settlement or {}).get("refund"),
                "days": (t - c.request_date).days,
            }
        )
    workload: dict = defaultdict(lambda: defaultdict(int))
    for c in accepted:
        if c.owner_id:
            workload[c.owner_id]["cases"] += 1
    for x in open_t:
        if x.owner_id:
            workload[x.owner_id]["open_tickets"] += 1
        if x.owner_id and ticket_svc.sla(x, None, cfg["at_risk_pct"])["resolution_breached"]:
            workload[x.owner_id]["breached_tickets"] += 1
    for d in defects:
        if d.owner_id:
            workload[d.owner_id]["open_defects"] += 1
    for cid, fu in latest.items():
        owner = by_case[cid].owner_id
        if owner and fu.next_follow_up_on and fu.next_follow_up_on <= t:
            workload[owner]["follow_ups_due"] += 1
    closed_t = (
        [
            x
            for x in tickets
            if x.status == TicketStatus.closed
            and x.owner_id
            and f.in_period(x.closed_at.astimezone(IST).date())
        ]
        if (f.period_from or f.period_to)
        else [
            x
            for x in tickets
            if x.status == TicketStatus.closed and x.owner_id and _age(x.closed_at) <= 30
        ]
    )
    for x in closed_t:
        workload[x.owner_id]["tickets_closed"] += 1
    names = (
        {
            u.id: (u.full_name, u.role.value)
            for u in await db.scalars(select(User).where(User.id.in_(list(workload))))
        }
        if workload
        else {}
    )
    return {
        "handover_pending": [{**_row(c), "days": _age(c.created_at)} for c in pending],
        "kyc_incomplete": kyc_incomplete,
        "agreements_by_stage": dict(by_stage),
        "agreements_pending": sorted(agreement_items, key=lambda x: -(x["days"] or 0)),
        "documents_awaiting_approval": awaiting,
        "documents_not_released": unreleased,
        "overdue_follow_ups": overdue_fu,
        "broken_promises": broken,
        "tickets_by_team": {k: dict(v) for k, v in by_team.items()},
        "sla_breaches": breaches,
        "requests_awaiting": requests_waiting,
        "possession_ready": ready,
        "possession_delays": sorted(delays, key=lambda x: -(x["days_open"] or 0)),
        "open_snags_defects": open_items,
        "cancellations": cancels_rows,
        "workload": sorted(
            [
                {"user": names.get(k, ("?", ""))[0], "role": names.get(k, ("?", ""))[1], **dict(v)}
                for k, v in workload.items()
            ],
            key=lambda x: -x.get("cases", 0),
        ),
    }


async def dashboard(db, f: Filters) -> dict:
    fin = await finance(db, f)
    ops = await operations(db, f)
    active = len(await _cases(db, f))
    agreements_pending = sum(ops["agreements_by_stage"].values())
    open_tickets = sum(v.get("total", 0) for v in ops["tickets_by_team"].values())
    return {
        "headline": {
            "active_accounts": active,
            "agreements_pending": agreements_pending,
            "overdue_receivables": fin["totals"]["overdue"],
            "open_tickets": open_tickets,
        },
        "money": {
            k: fin["totals"][k]
            for k in (
                "consideration",
                "outstanding",
                "collected",
                "awaiting_confirmation",
                "collection_efficiency_pct",
            )
        },
        "exceptions": [
            {
                "key": "overdue",
                "label": "Customers with overdue payments",
                "count": len(fin["ageing_items"]),
                "amount": fin["totals"]["overdue"],
                "report": "finance#ageing",
            },
            {
                "key": "broken_promises",
                "label": "Payment promises missed",
                "count": len(ops["broken_promises"]),
                "report": "operations#broken_promises",
            },
            {
                "key": "sla",
                "label": "Tickets past their SLA",
                "count": len(ops["sla_breaches"]),
                "report": "operations#sla_breaches",
            },
            {
                "key": "handover_pending",
                "label": "Bookings handed over but not accepted",
                "count": len(ops["handover_pending"]),
                "report": "operations#handover_pending",
            },
            {
                "key": "kyc",
                "label": "Customers with incomplete KYC",
                "count": len(ops["kyc_incomplete"]),
                "report": "operations#kyc_incomplete",
            },
            {
                "key": "docs",
                "label": "Documents awaiting approval",
                "count": len(ops["documents_awaiting_approval"]),
                "report": "operations#documents_awaiting_approval",
            },
            {
                "key": "follow_ups",
                "label": "Overdue follow-ups",
                "count": len(ops["overdue_follow_ups"]),
                "report": "operations#overdue_follow_ups",
            },
            {
                "key": "unconfirmed",
                "label": "Receipts waiting for confirmation",
                "count": sum(1 for c in fin["customers"] if c["pending_confirmation"]),
                "amount": fin["totals"]["awaiting_confirmation"],
                "report": "finance#customers",
            },
            {
                "key": "possession_ready",
                "label": "Units ready for possession",
                "count": len(ops["possession_ready"]),
                "report": "operations#possession_ready",
            },
            {
                "key": "snags",
                "label": "Overdue snags and defects",
                "count": sum(1 for x in ops["open_snags_defects"] if x["overdue"]),
                "report": "operations#open_snags_defects",
            },
            {
                "key": "refunds",
                "label": "Refunds pending",
                "count": len(fin["refunds_pending"]),
                "amount": sum(r["refund"] for r in fin["refunds_pending"]),
                "report": "finance#refunds_pending",
            },
        ],
        "upcoming": {
            k: {"count": v["count"], "amount": v["amount"]} for k, v in fin["upcoming"].items()
        },
        "ageing": fin["ageing"],
    }


async def take_snapshot(db, on: date | None = None) -> int:
    """Nightly: the headline figures for every project and in total, kept so past positions can be compared."""
    from app.models.mis import MisSnapshot
    from app.models.project import Project

    on = on or today()
    n = 0
    for pid in [None, *[p.id for p in await db.scalars(select(Project))]]:
        d = await dashboard(db, Filters(project_id=pid))
        data = {**d["headline"], **d["money"], "ageing": d["ageing"]}
        existing = await db.scalar(
            select(MisSnapshot).where(
                MisSnapshot.taken_on == on,
                MisSnapshot.project_id.is_(None) if pid is None else MisSnapshot.project_id == pid,
            )
        )
        if existing:
            existing.data = data
        else:
            db.add(MisSnapshot(taken_on=on, project_id=pid, data=data))
        n += 1
    return n


_ = (Demand, DemandStatus, Disbursement)
