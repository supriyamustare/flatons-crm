from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role
from tests import test_ledger
from tests.test_ledger import PAID, TODAY, generated

case = test_ledger.case  # the same booked, accepted case (a fixture)

STAGE1, STAGE2 = 322_500 + 3_225, 322_500 + 3_225  # Booking and Registration, each 10% + 1% GST


async def receipts(c, case_id):
    return (await c.get(f"/api/post-sales/cases/{case_id}/receipts")).json()


async def checker(login_as):
    chk, _ = await login_as(Role.finance_approver)
    return chk


def rec(amount, mode="neft", ref="UTR1", **kw):
    return {
        "amount": amount,
        "received_on": TODAY.isoformat(),
        "mode": mode,
        "reference": ref,
        **kw,
    }


async def test_booking_amount_becomes_a_receipt_waiting_for_confirmation(login_as, case):
    fin, fin_user, _ = await generated(login_as, case)
    data = await receipts(fin, case)
    r = data["receipts"][0]
    assert (r["amount"], r["status"], r["from_booking"], r["recorded_by"]["id"]) == (
        PAID,
        "recorded",
        True,
        fin_user.id,
    )
    assert r["matches"] == [{"stage_seq": 1, "charge_head": None, "amount": PAID}]
    assert data["balances"]["received"] == 0 and data["balances"]["pending_confirmation"] == PAID
    await fin.post(
        f"/api/post-sales/cases/{case}/ledger/generate"
    )  # generating again doesn't duplicate it
    assert len((await receipts(fin, case))["receipts"]) == 1


async def test_maker_checker_and_auto_matching(login_as, db, case):
    fin, _, _ = await generated(login_as, case)
    chk = await checker(login_as)
    booking = (await receipts(fin, case))["receipts"][0]["id"]
    assert (
        await fin.post(f"/api/post-sales/cases/{case}/receipts/{booking}/confirm")
    ).status_code == 403  # makers can't confirm
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{booking}/confirm")
    # Rs 3,30,000: Rs 3,225 finishes the booking stage, Rs 3,26,775 covers Registration fully... and Rs 0 left over
    data = (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts",
            json=rec(3_225 + STAGE2 + 1_000, ref="utr-2001"),
        )
    ).json()
    new = data["receipts"][0]
    assert new["reference"] == "UTR-2001" and new["status"] == "recorded"
    assert new["matches"] == [
        {"stage_seq": 1, "charge_head": None, "amount": 3_225},
        {"stage_seq": 2, "charge_head": None, "amount": STAGE2},
        {"stage_seq": 3, "charge_head": None, "amount": 1_000},
    ]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{new['id']}/confirm")
    data = await receipts(chk, case)
    stages = {s["seq"]: s for s in data["stages"]}
    assert (
        stages[1]["outstanding"] == 0
        and stages[2]["outstanding"] == 0
        and stages[3]["paid"] == 1_000
    )
    assert (
        data["balances"]["currently_demanded"] == 0
        and data["balances"]["received"] == PAID + 3_225 + STAGE2 + 1_000
    )
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "receipt.confirmed"))


async def test_an_admin_cannot_confirm_what_they_recorded(login_as, case):
    admin, _ = await login_as(Role.admin)
    await admin.post(f"/api/post-sales/cases/{case}/ledger/generate")
    rid = (await receipts(admin, case))["receipts"][0]["id"]
    r = await admin.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    assert r.status_code == 403 and "can't confirm" in r.text


async def test_matching_by_hand_and_limits(login_as, case):
    fin, _, _ = await generated(login_as, case)
    r = await fin.post(
        f"/api/post-sales/cases/{case}/receipts",
        json=rec(225_800, ref="UTR-SD", matches=[{"charge_head": "stamp_duty", "amount": 225_800}]),
    )
    assert r.status_code == 201 and r.json()["other_charges"][0]["head"] in (
        "stamp_duty",
        "registration",
        "legal",
    )
    for bad, msg in (
        (
            [{"stage_seq": 1, "amount": 5_000}],
            "only Rs 3,225 is still unpaid",
        ),  # booking receipt already holds Rs 3,22,500
        ([{"stage_seq": 2, "amount": 400_000}], "matched more than the receipt"),
        ([{"charge_head": "base_price", "amount": 1_000}], "statutory and other charges"),
        ([{"stage_seq": 99, "amount": 1_000}], "no stage 99"),
        ([{"charge_head": "stamp_duty", "amount": 1}], "only Rs 0 is still unpaid"),
    ):
        r = await fin.post(
            f"/api/post-sales/cases/{case}/receipts",
            json=rec(300_000, ref=f"UTR-X{len(msg)}", matches=bad),
        )
        assert r.status_code == 422 and msg in r.text, (bad, r.text)
    r = await fin.post(
        f"/api/post-sales/cases/{case}/receipts", json=rec(50_000, ref="UTR-ADV", matches=[])
    )
    assert r.json()["receipts"][0]["matched"] == 0  # all unapplied: an advance


@pytest.mark.parametrize(
    "body,msg",
    [
        (rec(200_000, mode="cash", ref=None), "Cash of Rs 2,00,000 or more"),
        (rec(5_000, mode="cheque", ref=None), "cheque number, UTR or transaction reference"),
        (
            {**rec(5_000), "received_on": (TODAY + timedelta(days=1)).isoformat()},
            "can't be in the future",
        ),
    ],
)
async def test_recording_rules(login_as, case, body, msg):
    fin, _, _ = await generated(login_as, case)
    r = await fin.post(f"/api/post-sales/cases/{case}/receipts", json=body)
    assert r.status_code == 422 and msg in r.text


async def test_duplicates_bounces_and_reversals(login_as, case):
    fin, _, _ = await generated(login_as, case)
    chk = await checker(login_as)
    assert (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts", json=rec(10_000, mode="cash", ref=None)
        )
    ).status_code == 201  # small cash is fine
    cheque = (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts", json=rec(100_000, mode="cheque", ref="000123")
        )
    ).json()["receipts"][0]
    assert (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts", json=rec(100_000, mode="cheque", ref="000123")
        )
    ).status_code == 409
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{cheque['id']}/confirm")
    assert (
        await chk.post(
            f"/api/post-sales/cases/{case}/receipts/{cheque['id']}/bounce", json={"reason": "no"}
        )
    ).status_code == 422
    data = (
        await chk.post(
            f"/api/post-sales/cases/{case}/receipts/{cheque['id']}/bounce",
            json={"reason": "Insufficient funds"},
        )
    ).json()
    bounced = next(x for x in data["receipts"] if x["id"] == cheque["id"])
    assert (
        bounced["status"] == "bounced"
        and bounced["void_reason"] == "Insufficient funds"
        and data["balances"]["received"] == 0
    )
    # the same cheque can be presented again after bouncing
    assert (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts", json=rec(100_000, mode="cheque", ref="000123")
        )
    ).status_code == 201
    upi = (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts", json=rec(1_000, mode="upi", ref="UPI-9")
        )
    ).json()["receipts"][0]
    assert (
        await chk.post(
            f"/api/post-sales/cases/{case}/receipts/{upi['id']}/bounce",
            json={"reason": "Wrong entry"},
        )
    ).status_code == 422
    assert (
        await chk.post(
            f"/api/post-sales/cases/{case}/receipts/{upi['id']}/reverse",
            json={"reason": "Wrong entry"},
        )
    ).status_code == 422  # not confirmed yet
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{upi['id']}/confirm")
    data = (
        await chk.post(
            f"/api/post-sales/cases/{case}/receipts/{upi['id']}/reverse",
            json={"reason": "Entered twice"},
        )
    ).json()
    assert next(x for x in data["receipts"] if x["id"] == upi["id"])["status"] == "reversed"
    assert len(data["receipts"]) == 5  # nothing is ever deleted


async def test_loan_disbursements(login_as, case):
    fin, _, _ = await generated(login_as, case)
    chk = await checker(login_as)
    r = await fin.post(
        f"/api/post-sales/cases/{case}/receipts", json=rec(1_000_000, ref="HDFC-D1", source="loan")
    )
    assert r.status_code == 422 and "sanctioned loan" in r.text
    await fin.put(
        f"/api/post-sales/cases/{case}/ledger/funding",
        json={"loan_sanctioned": 2_500_000, "lender": "HDFC Bank"},
    )
    rid = (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts",
            json=rec(1_000_000, ref="HDFC-D1", source="loan"),
        )
    ).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    b = (await receipts(chk, case))["balances"]
    assert (
        b["loan_disbursed"] == 1_000_000
        and b["loan_not_disbursed"] == 1_500_000
        and b["received_own"] == 0
    )


async def test_ledger_edits_cant_fall_below_matched_amounts(login_as, case):
    fin, _, led = await generated(login_as, case)
    items = [
        {k: i[k] for k in ("name", "amount", "gst", "trigger_type", "due_date", "milestone")}
        for i in led["schedule"]
    ]
    items[0]["amount"] = 100_000  # the booking receipt holds Rs 3,22,500 against this stage
    r = await fin.put(f"/api/post-sales/cases/{case}/ledger/schedule", json=items)
    assert r.status_code == 422 and "are matched to Booking" in r.text
    await fin.post(
        f"/api/post-sales/cases/{case}/receipts",
        json=rec(10_000, ref="UTR-L", matches=[{"charge_head": "legal", "amount": 10_000}]),
    )
    charges = [
        {
            "head": c["head"],
            "label": c["label"],
            "amount": 5_000 if c["head"] == "legal" else c["amount"],
        }
        for c in led["charges"]
    ]
    r = await fin.put(f"/api/post-sales/cases/{case}/ledger/charges", json=charges)
    assert r.status_code == 422 and "matched to legal" in r.text


async def test_who_can_see_and_do_what(login_as, case):
    await generated(login_as, case)
    for role, view, record in (
        (Role.postsales_exec, 200, 403),
        (Role.auditor, 200, 403),
        (Role.finance_approver, 200, 403),
        (Role.legal, 403, 403),
        (Role.executive, 403, 403),
    ):
        c, _ = await login_as(role)
        assert (await c.get(f"/api/post-sales/cases/{case}/receipts")).status_code == view, role
        assert (
            await c.post(
                f"/api/post-sales/cases/{case}/receipts", json=rec(1_000, ref=f"R-{role.value}")
            )
        ).status_code == record, role
