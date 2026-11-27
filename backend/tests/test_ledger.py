import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Notification, PostSalesCase, Role, Unit
from app.models.ledger import Ledger, ScheduleItem, TriggerType
from app.services import ledger as svc
from tests.conftest import new_project

HABITAT = json.loads(
    (Path(__file__).parent.parent / "app" / "data" / "projects_seed.json").read_text()
)["projects"][0]["cost_sheet"]
TODAY = datetime.now(UTC).date()
PRICE, PAID = 3_225_000, 322_500


@pytest.fixture
async def case(db, login_as):
    """Habitat-style project (17 stages, 1% GST, 7% stamp duty), one booked unit, handover accepted."""
    admin, _ = await login_as(Role.admin)
    project = await new_project(db, "Habitat")
    project.cost_sheet = HABITAT
    await db.commit()
    b = (await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "Habitat"})).json()
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": 11, "floor_to": 11, "units_per_floor": 1, "unit_type": "studio"},
    )
    unit_id = await db.scalar(select(Unit.id))
    lead = (
        await admin.post(
            "/api/leads",
            json={
                "name": "Anita Desai",
                "mobile": "9000000001",
                "email": "m9000000001@example.com",
                "source": "99acres",
            },
        )
    ).json()["lead"]
    bk = (
        await admin.post(
            "/api/bookings",
            json={
                "lead_id": lead["id"],
                "unit_id": unit_id,
                "booking_date": TODAY.isoformat(),
                "agreed_price": PRICE,
                "booking_amount": PAID,
            },
        )
    ).json()
    case_id = await db.scalar(select(PostSalesCase.id).where(PostSalesCase.booking_id == bk["id"]))
    pse, _ = await login_as(Role.postsales_exec)
    await pse.post(f"/api/post-sales/cases/{case_id}/accept")
    return case_id


async def generated(login_as, case_id):
    fin, user = await login_as(Role.finance)
    r = await fin.post(f"/api/post-sales/cases/{case_id}/ledger/generate")
    assert r.status_code == 201, r.text
    return fin, user, r.json()


async def test_generate_from_the_cost_sheet(login_as, case):
    _, _, led = await generated(login_as, case)
    charges = {c["head"]: c["amount"] for c in led["charges"]}
    # agreed price; GST 1%; stamp duty 7% rounded up to Rs 100; registration capped at Rs 30,000; legal Rs 10,000
    assert charges == {
        "base_price": 3_225_000,
        "gst": 32_250,
        "stamp_duty": 225_800,
        "registration": 30_000,
        "legal": 10_000,
    }
    assert len(led["schedule"]) == 17 and led["schedule"][0]["name"] == "Booking"
    assert (
        led["schedule"][0]["trigger_type"] == "on_booking"
        and led["schedule"][0]["due_date"] == TODAY.isoformat()
    )
    assert all(
        i["trigger_type"] == "on_milestone"
        and i["milestone"] == i["name"]
        and i["due_date"] is None
        for i in led["schedule"][1:]
    )
    t = led["totals"]
    assert (
        t["schedule_amount"] == t["agreement_value"] == PRICE
        and t["schedule_gst"] == t["gst"] == 32_250
    )
    assert (
        t["total_payable"] == 3_225_000 + 32_250 + 225_800 + 30_000 + 10_000
        and led["problems"] == []
    )
    assert led["status"] == "draft" and led["can_edit"]


async def test_the_seven_balances(login_as, case):
    fin, _, led = await generated(login_as, case)
    b, total = led["balances"], led["totals"]["total_payable"]
    # The booking amount is a receipt waiting for confirmation: not counted yet
    assert (b["received"], b["pending_confirmation"], b["currently_demanded"]) == (
        0,
        PAID,
        322_500 + 3_225,
    )
    chk, _ = await login_as(Role.finance_approver)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    b = (await fin.get(f"/api/post-sales/cases/{case}/ledger")).json()["balances"]
    assert (
        b["received"] == PAID
        and b["total_outstanding"] == total - PAID
        and b["pending_confirmation"] == 0
    )
    assert b["currently_demanded"] == 3_225  # the booking stage's GST is still unpaid
    assert b["overdue"] == 0  # due today, not yet past
    assert b["own_contribution_required"] == total - PAID and b["loan_not_disbursed"] == 0
    assert (
        b["under_dispute"] == 0
        and b["other_charges"] == 225_800 + 30_000 + 10_000
        and b["unapplied"] == 0
    )
    r = await fin.put(
        f"/api/post-sales/cases/{case}/ledger/funding",
        json={"loan_sanctioned": 2_500_000, "lender": "HDFC Bank", "loan_reference": "HL-123"},
    )
    b = r.json()["balances"]
    assert (
        b["own_contribution_required"] == total - 2_500_000 - PAID
        and b["loan_not_disbursed"] == 2_500_000
    )


def test_overdue_counts_only_past_due_dates():
    ledger = Ledger(
        loan_sanctioned=0,
        charges=[],
        schedule=[
            ScheduleItem(
                seq=1,
                name="Booking",
                amount=100_000,
                gst=1_000,
                trigger_type=TriggerType.on_booking,
                due_date=TODAY - timedelta(days=40),
            ),
            ScheduleItem(
                seq=2,
                name="Plinth",
                amount=100_000,
                gst=1_000,
                trigger_type=TriggerType.on_date,
                due_date=TODAY - timedelta(days=5),
            ),
            ScheduleItem(
                seq=3,
                name="Slab",
                amount=100_000,
                gst=1_000,
                trigger_type=TriggerType.on_date,
                due_date=TODAY,
            ),
            ScheduleItem(
                seq=4,
                name="Later",
                amount=100_000,
                gst=1_000,
                trigger_type=TriggerType.on_milestone,
                due_date=None,
                milestone="OC",
            ),
        ],
    )
    b = svc.balances(ledger, received_own=120_000, today=TODAY)
    assert b.currently_demanded == 3 * 101_000 - 120_000  # three stages are due
    assert b.overdue == 2 * 101_000 - 120_000  # only two are past their date


async def test_schedule_must_match_and_maker_checker(login_as, db, case):
    fin, fin_user, led = await generated(login_as, case)
    charges = [
        {"head": c["head"], "label": c["label"], "amount": c["amount"]} for c in led["charges"]
    ]
    chk, _ = await login_as(
        Role.finance_approver
    )  # exists before submitting, so it gets the notification
    parking = {"head": "parking", "label": "Covered parking", "amount": 300_000}
    led = (
        await fin.put(f"/api/post-sales/cases/{case}/ledger/charges", json=[*charges, parking])
    ).json()
    assert any("must equal the agreement value" in p for p in led["problems"])
    assert (
        "GST charge is Rs 32,250; at 1% of the agreement value it should be Rs 35,250"
        in led["problems"]
    )
    r = await fin.post(f"/api/post-sales/cases/{case}/ledger/submit")
    assert r.status_code == 422 and "Can't submit yet" in r.text
    # Correct GST for the parking, and put parking (with its GST) into the last stage
    charges = [*[{**c, "amount": 35_250} if c["head"] == "gst" else c for c in charges], parking]
    led = (await fin.put(f"/api/post-sales/cases/{case}/ledger/charges", json=charges)).json()
    items = [
        {k: i[k] for k in ("name", "amount", "gst", "trigger_type", "due_date", "milestone")}
        for i in led["schedule"]
    ]
    items[-1]["amount"] += 300_000
    items[-1]["gst"] += 3_000
    led = (await fin.put(f"/api/post-sales/cases/{case}/ledger/schedule", json=items)).json()
    assert led["problems"] == []
    assert (await fin.post(f"/api/post-sales/cases/{case}/ledger/submit")).json()[
        "status"
    ] == "pending_approval"
    assert (
        await fin.put(f"/api/post-sales/cases/{case}/ledger/funding", json={})
    ).status_code == 422  # locked while pending
    assert (
        await fin.post(f"/api/post-sales/cases/{case}/ledger/approve")
    ).status_code == 403  # makers can't approve
    note = await db.scalar(select(Notification).where(Notification.type == "ledger_approval"))
    assert note is not None
    r = await chk.post(f"/api/post-sales/cases/{case}/ledger/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_by"]
    assert (
        await fin.put(f"/api/post-sales/cases/{case}/ledger/charges", json=charges)
    ).status_code == 422  # approved = locked
    assert (
        await chk.post(f"/api/post-sales/cases/{case}/ledger/reopen", json={"reason": "no"})
    ).status_code == 422  # reason too short
    r = await chk.post(
        f"/api/post-sales/cases/{case}/ledger/reopen",
        json={"reason": "Customer negotiated a discount"},
    )
    assert (
        r.json()["status"] == "draft"
        and r.json()["version"] == 2
        and r.json()["note"] == "Customer negotiated a discount"
    )
    history = [
        h["action"] for h in (await chk.get(f"/api/post-sales/cases/{case}")).json()["history"]
    ]
    assert history[-5:] == [
        "ledger_charges",
        "ledger_schedule",
        "ledger_submitted",
        "ledger_approved",
        "ledger_reopened",
    ]
    _ = fin_user


async def test_an_admin_cannot_approve_what_they_submitted(login_as, case):
    admin, _ = await login_as(Role.admin)
    assert (await admin.post(f"/api/post-sales/cases/{case}/ledger/generate")).status_code == 201
    assert (await admin.post(f"/api/post-sales/cases/{case}/ledger/submit")).status_code == 200
    r = await admin.post(f"/api/post-sales/cases/{case}/ledger/approve")
    assert r.status_code == 403 and "can't approve" in r.text
    chk, _ = await login_as(Role.finance_approver)
    r = await chk.post(
        f"/api/post-sales/cases/{case}/ledger/return", json={"reason": "Check the stamp duty"}
    )
    assert r.json()["status"] == "draft" and r.json()["note"] == "Check the stamp duty"


@pytest.mark.parametrize(
    "bad",
    [
        [{"head": "discount", "label": "Festive offer", "amount": 50_000}],
        [{"head": "parking", "label": "Parking", "amount": -1}],
    ],
)
async def test_charge_signs(login_as, case, bad):
    fin, _, _ = await generated(login_as, case)
    assert (
        await fin.put(f"/api/post-sales/cases/{case}/ledger/charges", json=bad)
    ).status_code == 422


async def test_a_date_stage_needs_its_date(login_as, case):
    fin, _, _ = await generated(login_as, case)
    r = await fin.put(
        f"/api/post-sales/cases/{case}/ledger/schedule",
        json=[{"name": "Plinth", "amount": 1, "trigger_type": "on_date"}],
    )
    assert r.status_code == 422 and "choose the due date" in r.text


async def test_who_can_see_and_change_the_ledger(login_as, case):
    await generated(login_as, case)
    for role, view, edit in (
        (Role.postsales_exec, 200, 403),
        (Role.auditor, 200, 403),
        (Role.management, 200, 403),
        (Role.finance_approver, 200, 403),
        (Role.legal, 403, 403),
        (Role.executive, 403, 403),
        (Role.site, 403, 403),
    ):
        c, _ = await login_as(role)
        assert (await c.get(f"/api/post-sales/cases/{case}/ledger")).status_code == view, role
        assert (
            await c.put(f"/api/post-sales/cases/{case}/ledger/funding", json={})
        ).status_code == edit, role


async def test_needs_an_accepted_handover(login_as, db, case):
    c = await db.get(PostSalesCase, case)
    c.status = "handover_pending"
    await db.commit()
    fin, _ = await login_as(Role.finance)
    r = await fin.post(f"/api/post-sales/cases/{case}/ledger/generate")
    assert r.status_code == 422 and "Accept the handover first" in r.text
    _ = date
