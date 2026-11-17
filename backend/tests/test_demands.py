from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Notification, PostSalesCase, Role
from app.models.ledger import Ledger
from tests import test_ledger
from tests.test_ledger import PAID, TODAY, generated

case = test_ledger.case  # booked Habitat-style unit (17 stages), handover accepted
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 64
PLINTH = 322_500 + 3_225
LEGAL = {
    "developer_legal_name": "Avnee Estates LLP",
    "rera_number": "P52100099999",
    "registered_address": "Kharadi, Pune 411014",
    "signatory_name": "Rahul Test",
    "signatory_designation": "Designated Partner",
    "gstin": "27ABCFA1234K1ZP",
}
BANK = {
    "bank_name": "HDFC Bank",
    "account_holder_name": "Avnee Estates LLP Habitat A/c",
    "account_number": "50200012345678",
    "ifsc": "HDFC0001234",
    "branch": "Kharadi",
}


async def project_id(db, case_id):
    c = await db.get(PostSalesCase, case_id)
    return c.booking.project_id


async def approved_ledger(login_as, case_id):
    fin, _, _ = await generated(login_as, case_id)
    chk, _ = await login_as(Role.finance_approver)
    await fin.post(f"/api/post-sales/cases/{case_id}/ledger/submit")
    assert (await chk.post(f"/api/post-sales/cases/{case_id}/ledger/approve")).status_code == 200
    return fin, chk


async def report(c, pid, name="Plinth", when=TODAY, files=1):
    return await c.post(
        f"/api/projects/{pid}/milestones/report",
        data={"name": name, "completed_on": when.isoformat(), "note": "Slab cast"},
        files=[("files", (f"site{i}.png", PNG + bytes([i]), "image/png")) for i in range(files)],
    )


async def test_milestones_come_from_the_payment_stages(login_as, db, case):
    pm, _ = await login_as(Role.project_manager)
    ms = (await pm.get(f"/api/projects/{await project_id(db, case)}/milestones")).json()
    assert (
        len(ms) == 16
        and ms[0]["name"] == "Registration"
        and ms[1]["name"] == "Plinth"
        and ms[-1]["name"] == "OC"
    )
    assert all(m["status"] == "planned" and m["can_report"] for m in ms)


async def test_reporting_rules(login_as, db, case):
    pid = await project_id(db, case)
    site, _ = await login_as(Role.site)
    _, crm = await login_as(Role.crm_manager)
    assert (await report(site, pid, name="Swimming pool")).status_code == 422
    assert (await report(site, pid, when=TODAY + timedelta(days=1))).status_code == 422
    assert (
        await site.post(
            f"/api/projects/{pid}/milestones/report",
            data={"name": "Plinth", "completed_on": TODAY.isoformat()},
        )
    ).status_code == 422  # no evidence
    ex, _ = await login_as(Role.executive)
    assert (await report(ex, pid)).status_code == 403
    r = await report(site, pid, files=2)
    assert (
        r.status_code == 200 and r.json()["status"] == "reported" and len(r.json()["evidence"]) == 2
    )
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == crm.id, Notification.type == "milestone_reported"
        )
    )
    assert (await site.get(r.json()["evidence"][0]["url"])).content.startswith(PNG)


async def test_verifying_demands_the_stage_and_drafts_demands(login_as, db, case):
    await approved_ledger(login_as, case)
    pid = await project_id(db, case)
    pm, _ = await login_as(Role.project_manager)
    m = (await report(pm, pid)).json()
    admin_pm = pm
    assert (
        await admin_pm.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")
    ).status_code == 403  # project managers can't verify
    crm, _ = await login_as(Role.crm_manager)
    r = await crm.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["cases"], v["demands"], v["ledgers_not_approved"], v["due_date"]) == (
        1,
        1,
        0,
        (TODAY + timedelta(days=15)).isoformat(),
    )
    led = (await crm.get(f"/api/post-sales/cases/{case}/ledger")).json()
    plinth = next(i for i in led["schedule"] if i["name"] == "Plinth")
    assert plinth["due_date"] == (TODAY + timedelta(days=15)).isoformat() and plinth["is_due"]
    # Demanded now (the booking receipt isn't confirmed, so the booking stage is still owed too); not overdue yet
    assert (
        led["balances"]["currently_demanded"] == (PAID + 3_225) + PLINTH
        and led["balances"]["overdue"] == 0
    )
    fin, _ = await login_as(Role.finance)
    d = (await fin.get(f"/api/post-sales/cases/{case}/demands")).json()["demands"][0]
    assert (
        d["stage_name"],
        d["stage_amount"],
        d["previous_dues"],
        d["total_due"],
        d["status"],
    ) == ("Plinth", PLINTH, PAID + 3_225, PLINTH + PAID + 3_225, "draft")


async def test_unapproved_ledgers_get_dates_but_no_demand(login_as, db, case):
    await generated(login_as, case)  # draft ledger
    pid = await project_id(db, case)
    site, _ = await login_as(Role.site)
    crm, _ = await login_as(Role.crm_manager)
    m = (await report(site, pid)).json()
    v = (await crm.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")).json()
    assert (v["cases"], v["demands"], v["ledgers_not_approved"]) == (1, 0, 1)


async def test_returning_a_milestone(login_as, db, case):
    pid = await project_id(db, case)
    site, site_user = await login_as(Role.site)
    crm, _ = await login_as(Role.crm_manager)
    m = (await report(site, pid)).json()
    r = await crm.post(
        f"/api/projects/{pid}/milestones/{m['id']}/return",
        json={"reason": "Photos don't show the slab"},
    )
    assert (
        r.json()["status"] == "planned"
        and r.json()["returned_reason"] == "Photos don't show the slab"
    )
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == site_user.id, Notification.type == "milestone_returned"
        )
    )
    assert (await report(site, pid)).json()["status"] == "reported"


async def test_demand_approval_letter_issue_and_reissue(login_as, db, case):
    fin, chk = await approved_ledger(login_as, case)
    pid = await project_id(db, case)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(
        f"/api/post-sales/cases/{case}/receipts/{rid}/confirm"
    )  # booking amount received
    site, _ = await login_as(Role.site)
    crm, _ = await login_as(Role.crm_manager)
    m = (await report(site, pid)).json()
    await crm.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")
    d = (await fin.get(f"/api/post-sales/cases/{case}/demands")).json()["demands"][0]
    # Can't submit until the project's legal and bank details are complete
    r = await fin.post(f"/api/post-sales/cases/{case}/demands/{d['id']}/submit")
    assert r.status_code == 422 and "Complete the project's details first" in r.text
    admin, _ = await login_as(Role.admin)
    await admin.put(f"/api/projects/{pid}/legal", json=LEGAL)
    await admin.put(f"/api/projects/{pid}/bank", json=BANK)
    data = (await fin.post(f"/api/post-sales/cases/{case}/demands/{d['id']}/submit")).json()
    d = data["demands"][0]
    assert (
        d["status"] == "pending_approval"
        and d["previous_dues"] == 3_225
        and d["total_due"] == PLINTH + 3_225
    )  # booking GST still owed
    assert (
        await fin.post(f"/api/post-sales/cases/{case}/demands/{d['id']}/approve")
    ).status_code == 403
    assert (await chk.post(f"/api/post-sales/cases/{case}/demands/{d['id']}/approve")).json()[
        "demands"
    ][0]["status"] == "approved"
    letter = (await fin.get(f"/api/post-sales/cases/{case}/demands/{d['id']}/letter")).json()
    assert (
        letter["draft"] is False
        and letter["developer"]["name"] == "Avnee Estates LLP"
        and letter["bank"]["account"] == "50200012345678"
    )
    assert letter["total_due"] == PLINTH + 3_225 and letter["stage"] == "Plinth"
    # Frozen: later changes to the project's details don't alter an approved letter
    await admin.put(
        f"/api/projects/{pid}/legal",
        json={**LEGAL, "developer_legal_name": "Avnee Estates Pvt Ltd"},
    )
    assert (await fin.get(f"/api/post-sales/cases/{case}/demands/{d['id']}/letter")).json()[
        "developer"
    ]["name"] == "Avnee Estates LLP"
    pse, _ = await login_as(Role.postsales_exec)
    r = await pse.post(
        f"/api/post-sales/cases/{case}/demands/{d['id']}/issue", json={"method": "email"}
    )
    issued = r.json()["demands"][0]
    assert (
        issued["status"] == "issued"
        and issued["issue_method"] == "email"
        and issued["payment"] == "unpaid"
    )
    # A correction: cancel with a reason and reissue as version 2 (the old one stays)
    r = await chk.post(
        f"/api/post-sales/cases/{case}/demands/{d['id']}/cancel",
        json={"reason": "Wrong customer address"},
    )
    ds = r.json()["demands"]
    assert [(x["version"], x["status"]) for x in ds] == [(2, "draft"), (1, "cancelled")]
    assert (
        ds[0]["supersedes"] == issued["demand_no"]
        and ds[1]["cancel_reason"] == "Wrong customer address"
    )


async def test_creating_a_demand_by_hand(login_as, case):
    fin, _ = await approved_ledger(login_as, case)
    data = (await fin.get(f"/api/post-sales/cases/{case}/demands")).json()
    assert [s["name"] for s in data["can_create"]] == ["Booking"]  # the only demanded stage so far
    assert (
        await fin.post(f"/api/post-sales/cases/{case}/demands", json={"stage_seq": 1})
    ).status_code == 201
    assert (
        await fin.post(f"/api/post-sales/cases/{case}/demands", json={"stage_seq": 1})
    ).status_code == 409
    r = await fin.post(f"/api/post-sales/cases/{case}/demands", json={"stage_seq": 3})
    assert r.status_code == 422 and "isn't demanded yet" in r.text


async def test_ledger_edits_keep_milestone_dates(login_as, db, case):
    fin, chk = await approved_ledger(login_as, case)
    pid = await project_id(db, case)
    site, _ = await login_as(Role.site)
    crm, _ = await login_as(Role.crm_manager)
    m = (await report(site, pid)).json()
    await crm.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")
    await chk.post(f"/api/post-sales/cases/{case}/ledger/reopen", json={"reason": "Add parking"})
    led = (await fin.get(f"/api/post-sales/cases/{case}/ledger")).json()
    items = [
        {k: i[k] for k in ("name", "amount", "gst", "trigger_type", "due_date", "milestone")}
        for i in led["schedule"]
    ]
    await fin.put(f"/api/post-sales/cases/{case}/ledger/schedule", json=items)
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case))
    await db.refresh(ledger)
    plinth = next(i for i in ledger.schedule if i.name == "Plinth")
    assert plinth.demanded_on == TODAY and plinth.due_date == TODAY + timedelta(days=15)


@pytest.mark.parametrize(
    "role,code",
    [(Role.legal, 403), (Role.executive, 403), (Role.auditor, 200), (Role.postsales_exec, 200)],
)
async def test_who_can_see_demands(login_as, case, role, code):
    await generated(login_as, case)
    c, _ = await login_as(role)
    assert (await c.get(f"/api/post-sales/cases/{case}/demands")).status_code == code


async def test_nobody_verifies_their_own_report_not_even_an_admin(login_as, db, case):
    pid = await project_id(db, case)
    admin, _ = await login_as(Role.admin)
    m = (await report(admin, pid)).json()
    assert m["can_verify"] is False
    r = await admin.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")
    assert r.status_code == 403 and "can't verify" in r.text
    other, _ = await login_as(Role.admin)
    assert (await other.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")).status_code == 200


@pytest.mark.parametrize("role", [Role.site, Role.project_manager, Role.crm_manager])
async def test_post_sales_staff_can_see_floor_plans(login_as, db, case, role):
    c, _ = await login_as(role)
    assert (
        await c.get(f"/api/projects/{await project_id(db, case)}/floor-plans")
    ).status_code == 200
