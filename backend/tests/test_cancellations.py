from datetime import timedelta

from sqlalchemy import func, select

from app.models import PostSalesCase, Role, Unit
from app.models.booking import Booking
from app.models.payment import Receipt
from tests import test_ledger
from tests.test_demands import approved_ledger
from tests.test_ledger import PAID, TODAY

case = test_ledger.case
REQ = {
    "initiated_by": "customer",
    "reason_code": "loan_rejected",
    "reason": "HDFC rejected the home loan; customer cannot fund the balance",
}


async def st(c, case_id):
    return (await c.get(f"/api/post-sales/cases/{case_id}/cancellation")).json()


async def reviewed(login_as, case_id):
    pse, _ = await login_as(Role.postsales_exec)
    assert (
        await pse.post(f"/api/post-sales/cases/{case_id}/cancellation", json=REQ)
    ).status_code == 201
    legal, _ = await login_as(Role.legal)
    crm, _ = await login_as(Role.crm_manager)
    await legal.post(
        f"/api/post-sales/cases/{case_id}/cancellation/review/legal",
        json={
            "note": "Clause 12 applies",
            "contract_clause": "Clause 12.2 (cancellation by allottee)",
        },
    )
    s = (
        await crm.post(
            f"/api/post-sales/cases/{case_id}/cancellation/review/commercial",
            json={"note": "Accept; resale demand is good"},
        )
    ).json()
    assert s["cancellation"]["status"] == "reviewed"
    return pse, crm


async def test_the_full_controlled_workflow(login_as, db, case):
    fin, chk = await approved_ledger(login_as, case)
    pse, _ = await login_as(Role.postsales_exec)
    assert (
        await pse.post(
            f"/api/post-sales/cases/{case}/cancellation",
            json={**REQ, "request_date": (TODAY + timedelta(days=1)).isoformat()},
        )
    ).status_code == 422
    assert (
        await pse.post(
            f"/api/post-sales/cases/{case}/cancellation",
            json={**REQ, "supporting_document_ids": [999]},
        )
    ).status_code == 422
    s = (await pse.post(f"/api/post-sales/cases/{case}/cancellation", json=REQ)).json()
    assert (
        s["cancellation"]["number"].startswith("CXL-")
        and s["cancellation"]["status"] == "requested"
    )
    assert (
        await pse.post(f"/api/post-sales/cases/{case}/cancellation", json=REQ)
    ).status_code == 409
    legal, _ = await login_as(Role.legal)
    r = await legal.post(
        f"/api/post-sales/cases/{case}/cancellation/review/legal",
        json={"note": "Clause 12 applies"},
    )
    assert r.status_code == 422 and "contract clause" in r.text
    await legal.post(
        f"/api/post-sales/cases/{case}/cancellation/review/legal",
        json={"note": "Clause 12 applies", "contract_clause": "Clause 12.2"},
    )
    crm, _ = await login_as(Role.crm_manager)
    await crm.post(
        f"/api/post-sales/cases/{case}/cancellation/review/commercial", json={"note": "Accept"}
    )
    ded = [
        {
            "label": "Forfeiture: 10% of booking amount",
            "amount": 32_250,
            "basis": "Clause 12.2: 10% of the amount paid",
        }
    ]
    r = await fin.put(
        f"/api/post-sales/cases/{case}/cancellation/settlement", json={"deductions": ded}
    )
    assert (
        r.status_code == 422 and "need confirming" in r.text
    )  # step 5: checked against actual receipts
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    s = (
        await fin.put(
            f"/api/post-sales/cases/{case}/cancellation/settlement", json={"deductions": ded}
        )
    ).json()["cancellation"]["settlement"]
    assert (s["snapshot"]["received"], s["total_deductions"], s["refund"]) == (
        PAID,
        32_250,
        PAID - 32_250,
    )
    assert (
        await fin.post(f"/api/post-sales/cases/{case}/cancellation/approve/finance", json={})
    ).status_code == 403  # preparer / wrong role
    await chk.post(
        f"/api/post-sales/cases/{case}/cancellation/approve/finance",
        json={"note": "Matches receipts"},
    )
    mgmt, _ = await login_as(Role.management)
    s = (
        await mgmt.post(f"/api/post-sales/cases/{case}/cancellation/approve/management", json={})
    ).json()
    assert s["cancellation"]["status"] == "approved"
    await pse.post(
        f"/api/post-sales/cases/{case}/cancellation/communicated",
        json={"on": TODAY.isoformat(), "via": "email"},
    )
    bank = {
        "payee": "Anita Desai",
        "bank": "HDFC Bank",
        "account_number": "50100012345678",
        "ifsc": "HDFC0001234",
        "method": "cancelled_cheque",
    }
    assert (
        await fin.put(
            f"/api/post-sales/cases/{case}/cancellation/refund-bank",
            json={**bank, "ifsc": "hdfc1234"},
        )
    ).status_code == 422
    s = (await fin.put(f"/api/post-sales/cases/{case}/cancellation/refund-bank", json=bank)).json()
    assert (
        s["cancellation"]["refund_bank"]["account_masked"] == "••••5678"
        and "account_enc" not in s["cancellation"]["refund_bank"]
    )
    assert (
        await fin.post(f"/api/post-sales/cases/{case}/cancellation/refund-bank/verify")
    ).status_code == 403
    await chk.post(f"/api/post-sales/cases/{case}/cancellation/refund-bank/verify")
    r = await fin.post(
        f"/api/post-sales/cases/{case}/cancellation/refund-payment",
        json={"paid_on": TODAY.isoformat(), "amount": 1_000, "utr": "HDFCR0001"},
    )
    assert r.status_code == 422 and "approved Rs" in r.text
    await fin.post(
        f"/api/post-sales/cases/{case}/cancellation/refund-payment",
        json={"paid_on": TODAY.isoformat(), "amount": PAID - 32_250, "utr": "hdfcr0001"},
    )
    r = await crm.post(f"/api/post-sales/cases/{case}/cancellation/close")
    assert r.status_code == 422 and "unit released" in r.text and "refund reconciled" in r.text
    await chk.post(f"/api/post-sales/cases/{case}/cancellation/refund-payment/reconcile")
    receipts_before = await db.scalar(
        select(func.count()).select_from(Receipt).where(Receipt.case_id == case)
    )
    s = (await crm.post(f"/api/post-sales/cases/{case}/cancellation/release")).json()
    c = await db.get(PostSalesCase, case)
    await db.refresh(c)
    b = await db.get(Booking, c.booking_id)
    await db.refresh(b)
    unit = await db.get(Unit, b.unit_id)
    await db.refresh(unit)
    assert (
        b.status.value == "cancelled"
        and unit.status.value == "available"
        and c.status.value == "cancelled"
    )
    assert (
        await db.scalar(select(func.count()).select_from(Receipt).where(Receipt.case_id == case))
        == receipts_before
    )  # nothing erased
    s = (await crm.post(f"/api/post-sales/cases/{case}/cancellation/close")).json()
    assert s["cancellation"]["status"] == "closed"


async def test_the_two_approvals_are_different_people(login_as, case):
    await approved_ledger(login_as, case)
    await reviewed(login_as, case)
    admin, _ = await login_as(Role.admin)
    chk, _ = await login_as(Role.finance_approver)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    fin, _ = await login_as(Role.finance)
    await fin.put(f"/api/post-sales/cases/{case}/cancellation/settlement", json={"deductions": []})
    await admin.post(f"/api/post-sales/cases/{case}/cancellation/approve/finance", json={})
    r = await admin.post(f"/api/post-sales/cases/{case}/cancellation/approve/management", json={})
    assert r.status_code == 403 and "different people" in r.text


async def test_deductions_above_receipts_mean_nothing_to_refund(login_as, case):
    fin, chk = await approved_ledger(login_as, case)
    pse, crm = await reviewed(login_as, case)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    s = (
        await fin.put(
            f"/api/post-sales/cases/{case}/cancellation/settlement",
            json={
                "deductions": [
                    {
                        "label": "Brokerage recovered",
                        "amount": PAID + 50_000,
                        "basis": "Clause 12.4",
                    }
                ]
            },
        )
    ).json()["cancellation"]["settlement"]
    assert s["refund"] == 0 and s["balance_due_from_customer"] == 50_000
    await chk.post(f"/api/post-sales/cases/{case}/cancellation/approve/finance", json={})
    mgmt, _ = await login_as(Role.management)
    await mgmt.post(f"/api/post-sales/cases/{case}/cancellation/approve/management", json={})
    r = await fin.put(
        f"/api/post-sales/cases/{case}/cancellation/refund-bank",
        json={
            "payee": "Anita Desai",
            "bank": "HDFC Bank",
            "account_number": "50100012345678",
            "ifsc": "HDFC0001234",
            "method": "cancelled_cheque",
        },
    )
    assert r.status_code == 422 and "No refund is due" in r.text
    await pse.post(
        f"/api/post-sales/cases/{case}/cancellation/communicated",
        json={"on": TODAY.isoformat(), "via": "courier"},
    )
    await crm.post(f"/api/post-sales/cases/{case}/cancellation/release")
    assert (await crm.post(f"/api/post-sales/cases/{case}/cancellation/close")).json()[
        "cancellation"
    ]["status"] == "closed"


async def test_withdrawn_and_rejected_requests_stay_on_record(login_as, case):
    fin, chk = await approved_ledger(login_as, case)
    pse, crm = await reviewed(login_as, case)
    s = (
        await crm.post(
            f"/api/post-sales/cases/{case}/cancellation/withdraw",
            json={"reason": "Customer arranged funds"},
        )
    ).json()
    assert (
        s["cancellation"] is None
        and s["history"][0]["status"] == "withdrawn"
        and s["history"][0]["reason"] == "Customer arranged funds"
    )
    await reviewed(login_as, case)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    await fin.put(f"/api/post-sales/cases/{case}/cancellation/settlement", json={"deductions": []})
    s = (
        await chk.post(
            f"/api/post-sales/cases/{case}/cancellation/reject",
            json={"reason": "Forfeiture not applied per clause 12.2"},
        )
    ).json()
    assert [h["status"] for h in s["history"]] == ["rejected", "withdrawn"]
    assert (
        await pse.post(f"/api/post-sales/cases/{case}/cancellation", json=REQ)
    ).status_code == 201  # a fresh request is possible


async def test_the_sales_cancel_cannot_bypass_post_sales(login_as, db, case):
    c = await db.get(PostSalesCase, case)
    admin, _ = await login_as(Role.admin)
    r = await admin.post(
        f"/api/bookings/{c.booking_id}/cancel", json={"reason": "Customer changed mind"}
    )
    assert r.status_code == 422 and "post-sales cancellation workflow" in r.text
    ex, _ = await login_as(Role.executive)
    assert (await ex.get(f"/api/post-sales/cases/{case}/cancellation")).status_code == 403


async def test_release_needs_approval(login_as, case):
    await reviewed(login_as, case)
    crm, _ = await login_as(Role.crm_manager)
    r = await crm.post(f"/api/post-sales/cases/{case}/cancellation/release")
    assert r.status_code == 422 and "reviewed" in r.text


async def test_the_preparer_cannot_approve_even_with_both_roles(login_as, case):
    await approved_ledger(login_as, case)
    await reviewed(login_as, case)
    chk, _ = await login_as(Role.finance_approver)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    admin, _ = await login_as(
        Role.admin
    )  # admins may prepare and approve, but never both on one settlement
    await admin.put(
        f"/api/post-sales/cases/{case}/cancellation/settlement", json={"deductions": []}
    )
    for kind in ("finance", "management"):
        r = await admin.post(f"/api/post-sales/cases/{case}/cancellation/approve/{kind}", json={})
        assert r.status_code == 403 and "prepared the settlement" in r.text
