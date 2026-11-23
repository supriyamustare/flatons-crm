from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Notification, PostSalesCase, Role
from app.models.agreement import Agreement, AgreementStatus
from app.models.possession import PossessionFile
from tests import test_ledger
from tests.test_demands import BANK, LEGAL, project_id
from tests.test_handover import ALL
from tests.test_ledger import TODAY

case = test_ledger.case
PNG = b"\x89PNG\r\n\x1a\n"
WARRANTIES = [
    {
        "name": "Structural defects",
        "category": "structural",
        "period_months": 60,
        "starts_from": "possession",
        "basis": "Agreement clause 15 / RERA s.14(3)",
    },
    {
        "name": "Sanitary fittings",
        "category": "plumbing",
        "provider": "Jaquar",
        "period_months": 12,
        "starts_from": "possession",
        "basis": "Manufacturer warranty card",
    },
]


async def raise_(c, case_id, **kw):
    r = await c.post(
        "/api/defects",
        json={
            "case_id": case_id,
            "category": "plumbing",
            "description": "Leak under the kitchen sink",
            "location": "Kitchen",
            **kw,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def go(c, did, step, **data):
    return await c.post(f"/api/defects/{did}/step", json={"step": step, "data": data})


async def test_warranty_terms_are_per_project_and_never_deleted_once_used(login_as, db, case):
    pid = await project_id(db, case)
    pse, _ = await login_as(Role.postsales_exec)
    assert (await pse.put(f"/api/projects/{pid}/warranties", json=WARRANTIES)).status_code == 403
    legal, _ = await login_as(Role.legal)
    s = (await legal.put(f"/api/projects/{pid}/warranties", json=WARRANTIES)).json()
    assert [w["period_months"] for w in s["warranties"]] == [60, 12]
    wid = s["warranties"][1]["id"]
    await raise_(pse, case, warranty_item_id=wid)
    s = (
        await legal.put(
            f"/api/projects/{pid}/warranties",
            json=[{**WARRANTIES[0], "id": s["warranties"][0]["id"]}],
        )
    ).json()
    kept = next(w for w in s["warranties"] if w["id"] == wid)
    assert kept["active"] is False  # used by a defect: deactivated, not deleted


async def test_covered_defect_workflow_with_dispute(login_as, case):
    svc, me = await login_as(Role.after_sales)
    pm, _ = await login_as(Role.project_manager)
    pse, _ = await login_as(Role.postsales_exec)
    d = await raise_(pse, case, owner_id=me.id)
    did = d["id"]
    assert (
        d["number"].startswith("DEF-") and d["status"] == "raised" and d["next"] == []
    )  # post-sales raises; the service team works it
    assert (
        await go(
            svc, did, "schedule", visit_on=TODAY.isoformat(), availability="Weekdays after 5 pm"
        )
    ).status_code == 422  # acknowledge first
    await go(svc, did, "acknowledge", note="Noted")
    assert (
        await go(
            svc,
            did,
            "schedule",
            visit_on=(TODAY - timedelta(days=1)).isoformat(),
            availability="x x",
        )
    ).status_code == 422
    await go(
        svc,
        did,
        "schedule",
        visit_on=(TODAY + timedelta(days=1)).isoformat(),
        availability="Weekdays after 5 pm",
    )
    await go(svc, did, "diagnose", visited_on=TODAY.isoformat(), diagnosis="Loose waste coupling")
    d = (await go(svc, did, "responsibility", party="contractor", covered=True)).json()
    assert d["status"] == "responsibility_assigned"
    await go(
        svc,
        did,
        "start",
        action="repair",
        contractor="AquaFix Plumbing",
        target=(TODAY + timedelta(days=2)).isoformat(),
    )
    await go(
        svc, did, "complete", work="Coupling replaced and sealed", materials="1 waste coupling"
    )
    r = await go(svc, did, "quality")
    assert r.status_code == 403 and "Someone other than" in r.text
    await go(pm, did, "quality", note="Checked, dry")
    assert (
        await go(pse, did, "customer", response="disputed")
    ).status_code == 422  # what is disputed?
    d = (await go(pse, did, "customer", response="disputed", note="Still drips at night")).json()
    assert (d["status"], d["reopened_count"]) == ("reopened", 1) and "completed" not in d["steps"]
    await go(
        svc,
        did,
        "start",
        action="replace",
        contractor="AquaFix Plumbing",
        target=(TODAY + timedelta(days=2)).isoformat(),
    )
    await go(svc, did, "complete", work="Trap replaced")
    await go(pm, did, "quality")
    d = (await go(pse, did, "customer", response="accepted", note="Fine now")).json()
    assert (
        d["status"] == "closed"
        and d["closure_reason"] == "Rectified; customer confirmed"
        and len(d["steps"]["customer_history"]) == 2
    )


async def test_not_covered_needs_evidence_estimate_and_customer_approval(login_as, case):
    svc, _ = await login_as(Role.after_sales)
    pse, _ = await login_as(Role.postsales_exec)
    did = (await raise_(pse, case, category="fittings", description="Broken glass shelf"))["id"]
    await go(svc, did, "acknowledge")
    await go(svc, did, "schedule", visit_on=TODAY.isoformat(), availability="Saturday morning")
    await go(
        svc,
        did,
        "diagnose",
        visited_on=TODAY.isoformat(),
        diagnosis="Impact damage by the occupant",
    )
    r = await go(
        svc,
        did,
        "responsibility",
        party="customer",
        covered=False,
        reason="Damage caused after possession",
        estimate=1800,
    )
    assert r.status_code == 422 and "supporting evidence" in r.text
    await svc.post(
        f"/api/defects/{did}/files",
        data={"kind": "diagnosis"},
        files={"file": ("shelf.png", PNG + b"\x02" * 30, "image/png")},
    )
    assert (
        await go(
            svc,
            did,
            "responsibility",
            party="customer",
            covered=False,
            reason="Damage caused after possession",
        )
    ).status_code == 422  # estimate
    d = (
        await go(
            svc,
            did,
            "responsibility",
            party="customer",
            covered=False,
            reason="Damage caused after possession",
            estimate=1800,
        )
    ).json()
    assert d["status"] == "awaiting_customer_approval"
    assert (
        await go(
            svc, did, "start", action="replace", contractor="Glassworks", target=TODAY.isoformat()
        )
    ).status_code == 422  # not yet approved
    d = (await go(pse, did, "customer_approval", approved=False, on=TODAY.isoformat())).json()
    assert d["status"] == "closed" and "declined" in d["closure_reason"]


async def test_common_area_defects_and_facility_handover(login_as, db, case):
    pid = await project_id(db, case)
    crm, _ = await login_as(Role.crm_manager)
    r = await crm.post(
        "/api/defects",
        json={
            "project_id": pid,
            "category": "electrical",
            "description": "Lobby lights flicker",
            "location": "Tower A lobby",
        },
    )
    assert r.status_code == 201 and r.json()["unit"] == "Common area"
    s = (
        await crm.put(
            f"/api/projects/{pid}/facility-handover",
            json={
                "maintenance_start": TODAY.isoformat(),
                "maintenance_contacts": "FM desk 020-1234",
                "records_handed_to": "Habitat CHS",
                "records_handed_on": TODAY.isoformat(),
                "customer_guidance": "Raise service requests with the FM desk",
            },
        )
    ).json()
    assert (
        s["facility"]["records_handed_to"] == "Habitat CHS"
        and s["pending_common_area_defects"][0]["description"] == "Lobby lights flicker"
    )


async def test_handover_transfers_to_after_sales_with_real_warranty_dates(login_as, db, case):
    admin, _ = await login_as(Role.admin)
    pid = await project_id(db, case)
    await admin.put(f"/api/projects/{pid}/legal", json=LEGAL)
    await admin.put(f"/api/projects/{pid}/bank", json=BANK)
    await admin.put(f"/api/projects/{pid}/warranties", json=WARRANTIES)
    db.add(Agreement(case_id=case, status=AgreementStatus.registered, registration_no="HVL-9"))
    await db.commit()
    _, svc_user = await login_as(Role.after_sales)
    await admin.post(
        f"/api/post-sales/cases/{case}/possession/start",
        json={"reason": "Testing the after-sales transfer"},
    )
    crm, _ = await login_as(Role.crm_manager)
    await crm.post(
        f"/api/post-sales/cases/{case}/possession/exception",
        json={"reason": "MD approved possession for testing", "scope": ALL},
    )
    pse, _ = await login_as(Role.postsales_exec)
    await pse.post(
        f"/api/post-sales/cases/{case}/appointments",
        json={
            "kind": "possession",
            "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    site, _ = await login_as(Role.site)
    doc = (
        await site.post(
            f"/api/post-sales/cases/{case}/documents",
            data={
                "category": "possession",
                "doc_type": "Handover checklist",
                "title": "Signed checklist",
            },
            files={"file": ("cl.pdf", b"%PDF-1.4\nsigned", "application/pdf")},
        )
    ).json()["documents"][0]
    await pse.put(
        f"/api/post-sales/cases/{case}/possession/handover",
        json={
            "items": {
                "identity_verified": True,
                "keys_count": 2,
                "customer_acknowledged": True,
                "signed_checklist_document_id": doc["id"],
            }
        },
    )
    await pse.post(
        f"/api/post-sales/cases/{case}/possession/handover/complete",
        json={"actual_possession_on": TODAY.isoformat()},
    )
    f = await db.scalar(select(PossessionFile).where(PossessionFile.case_id == case))
    await db.refresh(f)
    assert f.after_sales_since is not None
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == svc_user.id, Notification.type == "after_sales_transfer"
        )
    )
    s = (await pse.get(f"/api/post-sales/cases/{case}/after-sales")).json()
    structural = next(w for w in s["warranties"] if w["name"] == "Structural defects")
    assert structural["start"] == TODAY.isoformat() and structural["in_warranty"] is True
    assert structural["end"] == (TODAY.replace(year=TODAY.year + 5) - timedelta(days=1)).isoformat()
    _ = PostSalesCase
