from datetime import timedelta

from sqlalchemy import select

from app.models import Notification, Role
from app.services.followups import run_reminders
from tests import test_ledger
from tests.test_ledger import TODAY, generated

case = test_ledger.case
LOAN = {
    "lender": "HDFC Bank",
    "application_no": "HL-TEST-001",
    "applied_amount": 2_600_000,
    "rm_name": "Suresh Iyer",
    "rm_phone": "9822011111",
    "rm_email": "suresh@example.com",
}


async def loan(c, case_id, **kw):
    return await c.post(f"/api/post-sales/cases/{case_id}/loan", json={**LOAN, **kw})


async def sanctioned(login_as, case_id):
    pse, _ = await login_as(Role.postsales_exec)
    await loan(pse, case_id, consent_on=TODAY.isoformat())
    r = await pse.put(
        f"/api/post-sales/cases/{case_id}/loan",
        json={
            **LOAN,
            "consent_on": TODAY.isoformat(),
            "sanctioned_amount": 2_500_000,
            "sanction_date": TODAY.isoformat(),
            "sanction_valid_until": (TODAY + timedelta(days=180)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    return pse


async def test_consent_first_and_the_stages_follow_what_is_recorded(login_as, case):
    pse, _ = await login_as(Role.postsales_exec)
    s = (await loan(pse, case)).json()
    assert s["stage"] == "details_captured" and "consent" in s["warnings"][0]
    r = await pse.post(
        f"/api/post-sales/cases/{case}/loan/doc-requests", json={"name": "Agreement copy"}
    )
    assert r.status_code == 422 and "consent" in r.text
    await pse.put(
        f"/api/post-sales/cases/{case}/loan", json={**LOAN, "consent_on": TODAY.isoformat()}
    )
    s = (
        await pse.post(
            f"/api/post-sales/cases/{case}/loan/doc-requests", json={"name": "Allotment letter"}
        )
    ).json()
    assert s["stage"] == "documents_requested"
    rid = s["doc_requests"][0]["id"]
    s = (
        await pse.post(f"/api/post-sales/cases/{case}/loan/doc-requests/{rid}/submitted", json={})
    ).json()
    assert (
        s["stage"] == "documents_submitted"
        and s["doc_requests"][0]["submitted_on"] == TODAY.isoformat()
    )
    s = (
        await pse.put(
            f"/api/post-sales/cases/{case}/loan",
            json={**LOAN, "consent_on": TODAY.isoformat(), "technical_status": "in_progress"},
        )
    ).json()
    assert s["stage"] == "bank_review" and [x["key"] for x in s["stages"] if x["done"]] == [
        "details_captured",
        "documents_requested",
        "documents_submitted",
    ]
    assert (await loan(pse, case)).status_code == 409  # one open loan per case


async def test_loan_details_are_checked(login_as, case):
    pse, _ = await login_as(Role.postsales_exec)
    await loan(pse, case)
    for bad, msg in (
        (
            {"sanctioned_amount": 3_000_000, "sanction_date": TODAY.isoformat()},
            "more than the amount applied for",
        ),
        ({"sanctioned_amount": 2_000_000}, "sanction date with the sanctioned amount"),
        (
            {
                "sanctioned_amount": 2_000_000,
                "sanction_date": TODAY.isoformat(),
                "sanction_valid_until": (TODAY - timedelta(days=1)).isoformat(),
            },
            "can't expire before",
        ),
        ({"rm_email": "not-an-email"}, "rm_email"),
        ({"consent_on": (TODAY + timedelta(days=1)).isoformat()}, "can't be in the future"),
    ):
        r = await pse.put(f"/api/post-sales/cases/{case}/loan", json={**LOAN, **bad})
        assert r.status_code == 422 and msg in r.text, (bad, r.text)


async def test_disbursement_to_reconciled_without_paying_demands(login_as, db, case):
    fin, _, led = await generated(login_as, case)
    pse = await sanctioned(login_as, case)
    s = (await pse.get(f"/api/post-sales/cases/{case}/loan")).json()
    assert any("ledger's loan is Rs 0 but Rs 2,500,000 is sanctioned" in w for w in s["warnings"])
    r = await pse.post(
        f"/api/post-sales/cases/{case}/loan/disbursements", json={"expected_amount": 2_600_000}
    )
    assert r.status_code == 422 and "more than the sanctioned" in r.text
    s = (
        await pse.post(
            f"/api/post-sales/cases/{case}/loan/disbursements",
            json={"request_no": "DR-1", "for_stage": "Plinth", "expected_amount": 1_000_000},
        )
    ).json()
    assert s["stage"] == "disbursement_requested"
    did = s["disbursements"][0]["id"]
    s = (
        await pse.put(
            f"/api/post-sales/cases/{case}/loan/disbursements/{did}",
            json={"status": "awaited", "expected_date": (TODAY + timedelta(days=5)).isoformat()},
        )
    ).json()
    assert s["stage"] == "disbursement_awaited"
    assert (
        await pse.post(
            f"/api/post-sales/cases/{case}/loan/disbursements/{did}/received",
            json={
                "actual_date": TODAY.isoformat(),
                "actual_amount": 1_000_000,
                "utr": "HDFC-UTR-1",
            },
        )
    ).status_code == 403
    s = (
        await fin.post(
            f"/api/post-sales/cases/{case}/loan/disbursements/{did}/received",
            json={
                "actual_date": TODAY.isoformat(),
                "actual_amount": 1_000_000,
                "utr": "hdfc-utr-1",
            },
        )
    ).json()
    d = s["disbursements"][0]
    assert (
        s["stage"] == "funds_received"
        and d["receipt_status"] == "recorded"
        and d["utr"] == "HDFC-UTR-1"
    )
    rec = (await fin.get(f"/api/post-sales/cases/{case}/receipts")).json()
    loan_r = next(x for x in rec["receipts"] if x["source"] == "loan")
    assert (
        loan_r["matches"] == [] and rec["balances"]["loan_disbursed"] == 0
    )  # not counted until confirmed; no demand paid automatically
    chk, _ = await login_as(Role.finance_approver)
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{loan_r['id']}/confirm")
    s = (await pse.get(f"/api/post-sales/cases/{case}/loan")).json()
    assert (
        s["stage"] == "reconciled"
        and s["loan"]["received_total"] == 1_000_000
        and s["loan"]["remaining"] == 1_500_000
    )
    assert (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["balances"][
        "loan_disbursed"
    ] == 1_000_000
    s2 = (
        await pse.post(
            f"/api/post-sales/cases/{case}/loan/disbursements", json={"expected_amount": 500_000}
        )
    ).json()
    d2 = s2["disbursements"][1]["id"]
    r = await fin.post(
        f"/api/post-sales/cases/{case}/loan/disbursements/{d2}/received",
        json={"actual_date": TODAY.isoformat(), "actual_amount": 500_000, "utr": "HDFC-UTR-1"},
    )
    assert r.status_code == 409  # the same UTR twice
    _ = led


async def test_who_sees_loan_data(login_as, case):
    await sanctioned(login_as, case)
    for role, code in (
        (Role.legal, 403),
        (Role.site, 403),
        (Role.executive, 403),
        (Role.auditor, 200),
        (Role.finance, 200),
        (Role.crm_manager, 200),
    ):
        c, _ = await login_as(role)
        assert (await c.get(f"/api/post-sales/cases/{case}/loan")).status_code == code, role


async def test_daily_loan_reminders(login_as, db, case):
    pse = await sanctioned(login_as, case)
    _, owner = await login_as(Role.postsales_exec)
    _, crm = await login_as(Role.crm_manager)
    soon = (TODAY + timedelta(days=15)).isoformat()
    await pse.put(
        f"/api/post-sales/cases/{case}/loan",
        json={
            **LOAN,
            "consent_on": TODAY.isoformat(),
            "sanctioned_amount": 2_500_000,
            "sanction_date": TODAY.isoformat(),
            "sanction_valid_until": soon,
            "owner_id": owner.id,
            "next_follow_up_on": TODAY.isoformat(),
        },
    )
    s = (
        await pse.post(
            f"/api/post-sales/cases/{case}/loan/disbursements",
            json={
                "expected_amount": 1_000_000,
                "expected_date": (TODAY - timedelta(days=8)).isoformat(),
            },
        )
    ).json()
    assert s["disbursements"][0]["delayed"] is True
    counts = await run_reminders(db, TODAY)
    await db.commit()
    assert (counts["loan_delays"], counts["loan_follow_ups"], counts["sanction_expiring"]) == (
        2,
        1,
        1,
    )  # delay: owner + CRM (8 days)
    for uid, kind in (
        (owner.id, "loan_disbursement_delayed"),
        (crm.id, "loan_disbursement_delayed"),
        (owner.id, "loan_follow_up_due"),
        (owner.id, "loan_sanction_expiring"),
    ):
        assert await db.scalar(
            select(Notification.id).where(Notification.user_id == uid, Notification.type == kind)
        ), kind
    assert (await run_reminders(db, TODAY))["loan_delays"] == 0  # once a day


async def test_closing_and_starting_again(login_as, case):
    pse = await sanctioned(login_as, case)
    assert (
        await pse.post(f"/api/post-sales/cases/{case}/loan/close", json={"reason": "no"})
    ).status_code == 422
    s = (
        await pse.post(
            f"/api/post-sales/cases/{case}/loan/close", json={"reason": "Customer switched to SBI"}
        )
    ).json()
    assert s["loan"] is None and s["history"][0]["close_reason"] == "Customer switched to SBI"
    assert (await loan(pse, case, lender="State Bank of India")).status_code == 201
