from datetime import UTC, datetime, timedelta

from app.models import PostSalesCase, Role
from app.models.agreement import Agreement, AgreementStatus
from tests import test_ledger
from tests.test_demands import BANK, LEGAL, approved_ledger, project_id, report
from tests.test_ledger import TODAY

case = test_ledger.case
PDF = b"%PDF-1.4\n"


async def oc_verified(login_as, db, case_id):
    pid = await project_id(db, case_id)
    site, _ = await login_as(Role.site)
    crm, _ = await login_as(Role.crm_manager)
    m = (await report(site, pid, name="OC")).json()
    await crm.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")
    return pid


async def st(c, case_id):
    return (await c.get(f"/api/post-sales/cases/{case_id}/possession")).json()


async def test_starting_follows_the_project_milestone(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    s = await st(pse, case)
    assert (s["trigger"], s["trigger_reached"], s["file"]) == ("OC", False, None)
    r = await pse.post(f"/api/post-sales/cases/{case}/possession/start", json={})
    assert r.status_code == 422 and "OC milestone is verified" in r.text
    admin, _ = await login_as(Role.admin)
    assert (
        await admin.post(f"/api/post-sales/cases/{case}/possession/start", json={})
    ).status_code == 422  # needs a reason
    r = await admin.post(
        f"/api/post-sales/cases/{case}/possession/start",
        json={"reason": "Customer relocating; OC expected next week"},
    )
    assert r.status_code == 201 and r.json()["file"]["start_reason"].startswith(
        "Customer relocating"
    )
    assert (
        await pse.post(f"/api/post-sales/cases/{case}/possession/start", json={})
    ).status_code == 409


async def test_finance_clearance_is_maker_checker(login_as, db, case):
    fin, chk = await approved_ledger(login_as, case)
    await oc_verified(login_as, db, case)
    pse, _ = await login_as(Role.postsales_exec)
    await pse.post(f"/api/post-sales/cases/{case}/possession/start", json={})
    s = await st(fin, case)
    f = s["file"]["financial"]
    assert (
        f["final_demand_raised"] is True and f["unconfirmed_receipts"] == 1 and f["outstanding"] > 0
    )
    r = await fin.post(f"/api/post-sales/cases/{case}/possession/finance/request-clearance")
    assert (
        r.status_code == 422 and "waiting for confirmation" in r.text and "confirm taxes" in r.text
    )
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    assert (
        await pse.put(
            f"/api/post-sales/cases/{case}/possession/finance", json={"taxes_confirmed": True}
        )
    ).status_code == 403
    await fin.put(
        f"/api/post-sales/cases/{case}/possession/finance",
        json={
            "charges_note": "Maintenance deposit added",
            "adjustments_note": "None",
            "taxes_confirmed": True,
            "payment_confirmed": True,
        },
    )
    # an open payment dispute blocks the request
    t = (
        await pse.post(
            f"/api/post-sales/cases/{case}/tickets",
            data={
                "category": "receipt",
                "title": "Missing receipt",
                "description": "Customer wants RCT copy",
            },
        )
    ).json()
    r = await fin.post(f"/api/post-sales/cases/{case}/possession/finance/request-clearance")
    assert r.status_code == 422 and t["ticket_no"] in r.text
    await pse.post(
        f"/api/tickets/{t['id']}/close",
        json={"closure_reason": "not_applicable", "note": "Receipt sent by email"},
    )
    assert (
        await fin.post(f"/api/post-sales/cases/{case}/possession/finance/request-clearance")
    ).status_code == 200
    r = await chk.post(f"/api/post-sales/cases/{case}/possession/finance/clear", json={})
    assert r.status_code == 422 and "still outstanding" in r.text
    s = (
        await chk.post(
            f"/api/post-sales/cases/{case}/possession/finance/clear",
            json={"note": "Balance payable at possession under clause 7"},
        )
    ).json()
    assert (
        s["file"]["clearance"]["cleared_by"]
        and s["file"]["clearance"]["snapshot"]["outstanding"] > 0
    )


async def test_requester_cannot_clear(login_as, db, case):
    await approved_ledger(login_as, case)
    admin, _ = await login_as(Role.admin)
    await admin.post(
        f"/api/post-sales/cases/{case}/possession/start",
        json={"reason": "Testing the clearance rule"},
    )
    c = await db.get(PostSalesCase, case)
    c.booking.booking_amount = c.booking.booking_amount  # no-op; keep the session warm
    chk, _ = await login_as(Role.finance_approver)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    await admin.put(
        f"/api/post-sales/cases/{case}/possession/finance",
        json={"taxes_confirmed": True, "payment_confirmed": True},
    )
    assert (
        await admin.post(f"/api/post-sales/cases/{case}/possession/finance/request-clearance")
    ).status_code == 200
    r = await admin.post(
        f"/api/post-sales/cases/{case}/possession/finance/clear",
        json={"note": "Payable at possession as agreed"},
    )
    assert r.status_code == 403 and "can't give it" in r.text


async def test_documents_and_unit_readiness(login_as, db, case):
    admin, _ = await login_as(Role.admin)
    await admin.post(
        f"/api/post-sales/cases/{case}/possession/start", json={"reason": "Testing the checklists"}
    )
    legal, _ = await login_as(Role.legal)
    r = await legal.put(
        f"/api/post-sales/cases/{case}/possession/documents",
        json={
            "items": [{"item": "Occupancy or completion certificate", "status": "not_applicable"}]
        },
    )
    assert r.status_code == 422 and "say why" in r.text
    assert (
        await legal.put(
            f"/api/post-sales/cases/{case}/possession/documents",
            json={"items": [{"item": "Pool certificate", "status": "available"}]},
        )
    ).status_code == 422
    s = (
        await legal.put(
            f"/api/post-sales/cases/{case}/possession/documents",
            json={"items": [{"item": "Executed agreement", "status": "available"}]},
        )
    ).json()
    assert (
        next(d for d in s["file"]["documents"] if d["item"] == "Executed agreement")["status"]
        == "available"
    )
    site, site_user = await login_as(Role.site)
    pm, pm_user = await login_as(Role.project_manager)
    r = await site.put(
        f"/api/post-sales/cases/{case}/possession/readiness",
        json={"items": [{"item": "Internal finishing inspected", "status": "issue"}]},
    )
    assert r.status_code == 422 and "describe the issue" in r.text
    assert (
        await site.post(
            f"/api/post-sales/cases/{case}/possession/snags",
            json={
                "description": "Hairline crack near window",
                "owner_id": site_user.id,
                "due_on": (TODAY - timedelta(days=1)).isoformat(),
            },
        )
    ).status_code == 422
    s = (
        await site.post(
            f"/api/post-sales/cases/{case}/possession/snags",
            json={
                "description": "Hairline crack near window",
                "location": "Living room",
                "owner_id": site_user.id,
                "due_on": (TODAY + timedelta(days=5)).isoformat(),
            },
        )
    ).json()
    sid = s["file"]["snags"][0]["id"]
    r = await pm.post(f"/api/post-sales/cases/{case}/possession/readiness/approve")
    assert (
        r.status_code == 422
        and "Items not OK" in r.text
        and "1 snag(s)" in r.text
        and "No inspection evidence" in r.text
    )
    all_ok = [{"item": i["item"], "status": "ok"} for i in s["file"]["readiness"]]
    await site.put(
        f"/api/post-sales/cases/{case}/possession/readiness",
        json={"items": all_ok, "meters": {"Electricity": "000123", "Water": "45.2"}},
    )
    await site.post(
        f"/api/post-sales/cases/{case}/possession/snags/{sid}",
        json={"status": "fixed", "note": "Filled and repainted"},
    )
    assert (
        await site.post(
            f"/api/post-sales/cases/{case}/possession/snags/{sid}", json={"status": "verified"}
        )
    ).status_code == 422  # fixer can't verify
    await pm.post(
        f"/api/post-sales/cases/{case}/possession/snags/{sid}", json={"status": "verified"}
    )
    await site.post(
        f"/api/post-sales/cases/{case}/documents",
        data={
            "category": "possession",
            "doc_type": "Inspection report",
            "title": "Unit 201 inspection",
        },
        files={"file": ("insp.pdf", PDF + b"inspection", "application/pdf")},
    )
    s = (await pm.post(f"/api/post-sales/cases/{case}/possession/readiness/approve")).json()
    assert s["file"]["readiness_approved_by"] and s["file"]["meters"]["Electricity"] == "000123"
    s = (
        await site.post(
            f"/api/post-sales/cases/{case}/possession/snags",
            json={
                "description": "Tap leaking",
                "owner_id": site_user.id,
                "due_on": (TODAY + timedelta(days=2)).isoformat(),
            },
        )
    ).json()
    assert s["file"]["readiness_approved_by"] is None  # a new snag withdraws the approval
    _ = pm_user


async def test_the_gate_guards_possession_appointments(login_as, db, case):
    admin, _ = await login_as(Role.admin)
    pid = await project_id(db, case)
    await admin.put(f"/api/projects/{pid}/legal", json=LEGAL)
    await admin.put(f"/api/projects/{pid}/bank", json=BANK)
    db.add(Agreement(case_id=case, status=AgreementStatus.registered, registration_no="HVL-1"))
    await db.commit()
    await admin.post(
        f"/api/post-sales/cases/{case}/possession/start",
        json={"reason": "Testing the possession gate"},
    )
    pse, _ = await login_as(Role.postsales_exec)
    when = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    r = await pse.post(
        f"/api/post-sales/cases/{case}/appointments", json={"kind": "possession", "starts_at": when}
    )
    assert (
        r.status_code == 422
        and "Finance clearance" in r.text
        and "Legal and statutory readiness" not in r.text
    )  # legal is met
    s = await st(admin, case)
    assert {c["key"]: c["met"] for c in s["file"]["gate"]["conditions"]}["legal"] is True
    crm, _ = await login_as(Role.crm_manager)
    assert (
        await pse.post(
            f"/api/post-sales/cases/{case}/possession/exception",
            json={"reason": "Customer must move in urgently", "scope": ["finance"]},
        )
    ).status_code == 403
    await crm.post(
        f"/api/post-sales/cases/{case}/possession/exception",
        json={
            "reason": "Customer must move in urgently; MD approved",
            "scope": ["finance", "readiness"],
        },
    )
    r = await pse.post(
        f"/api/post-sales/cases/{case}/appointments", json={"kind": "possession", "starts_at": when}
    )
    assert (
        r.status_code == 422 and "Possession documents" in r.text
    )  # the exception covers only what it names
    s = (
        await crm.post(
            f"/api/post-sales/cases/{case}/possession/exception",
            json={
                "reason": "Customer must move in urgently; MD approved all",
                "scope": [
                    "documents",
                    "finance",
                    "readiness",
                    "internal",
                    "communication",
                    "inspection",
                ],
            },
        )
    ).json()
    assert s["file"]["gate"]["open"] is True and s["file"]["exception"]["by_name"]
    assert (
        await pse.post(
            f"/api/post-sales/cases/{case}/appointments",
            json={"kind": "possession", "starts_at": when},
        )
    ).status_code == 201
    ex, _ = await login_as(Role.executive)
    assert (await ex.get(f"/api/post-sales/cases/{case}/possession")).status_code == 403
