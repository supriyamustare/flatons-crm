from datetime import UTC, datetime, timedelta

from app.models import PostSalesCase, Role
from app.models.agreement import Agreement, AgreementStatus
from tests import test_ledger
from tests.test_demands import BANK, LEGAL, project_id
from tests.test_ledger import TODAY

case = test_ledger.case
PNG = b"\x89PNG\r\n\x1a\n"
PDF = b"%PDF-1.4\n"
ALL = ["legal", "documents", "finance", "readiness", "internal", "communication", "inspection"]


async def opened(login_as, case_id):
    admin, _ = await login_as(Role.admin)
    await admin.post(
        f"/api/post-sales/cases/{case_id}/possession/start",
        json={"reason": "Testing inspection and handover"},
    )
    return admin


async def snag(c, case_id, owner_id, **kw):
    body = {
        "description": "Crack in the wall",
        "owner_id": owner_id,
        "due_on": (TODAY + timedelta(days=3)).isoformat(),
        **kw,
    }
    r = await c.post(f"/api/post-sales/cases/{case_id}/possession/snags", json=body)
    assert r.status_code == 201, r.text
    return r.json()["file"]["snags"][-1]


async def test_snag_register_rules(login_as, case):
    await opened(login_as, case)
    site, site_user = await login_as(Role.site)
    pm, _ = await login_as(Role.project_manager)
    s = await snag(
        site, case, site_user.id, severity="major", category="plumbing", location="Bathroom"
    )
    assert (s["category"], s["severity"], s["source"], s["status"]) == (
        "plumbing",
        "major",
        "internal",
        "open",
    )
    base = f"/api/post-sales/cases/{case}/possession/snags/{s['id']}"
    assert "Describe the rectification" in (await site.post(base, json={"status": "fixed"})).text
    r = await site.post(base, json={"status": "fixed", "note": "Pipe joint resealed"})
    assert r.status_code == 422 and "needs completion evidence" in r.text
    await site.post(
        f"{base}/evidence",
        data={"kind": "completion"},
        files={"file": ("done.png", PNG + b"\x01" * 30, "image/png")},
    )
    s = next(
        x
        for x in (
            await site.post(base, json={"status": "fixed", "note": "Pipe joint resealed"})
        ).json()["file"]["snags"]
        if x["id"] == s["id"]
    )
    assert (
        s["status"] == "fixed"
        and s["rectification"] == "Pipe joint resealed"
        and s["evidence"][0]["kind"] == "completion"
    )
    assert (
        await site.post(base, json={"status": "verified"})
    ).status_code == 422  # the fixer can't verify
    s = next(
        x
        for x in (await pm.post(base, json={"status": "verified"})).json()["file"]["snags"]
        if x["id"] == s["id"]
    )
    assert s["status"] == "closed" and s["closed_at"]  # internal snag: closes on verification
    s = next(
        x
        for x in (await pm.post(base, json={"status": "reopen", "note": "Leak is back"})).json()[
            "file"
        ]["snags"]
        if x["id"] == s["id"]
    )
    assert (s["status"], s["reopen_reason"], s["reopened_count"]) == ("open", "Leak is back", 1)


async def test_customer_snags_close_only_on_acceptance(login_as, case):
    await opened(login_as, case)
    pse, _ = await login_as(Role.postsales_exec)
    site, site_user = await login_as(Role.site)
    pm, _ = await login_as(Role.project_manager)
    s = await snag(pse, case, site_user.id, source="customer", description="Door doesn't latch")
    base = f"/api/post-sales/cases/{case}/possession/snags/{s['id']}"
    await site.post(base, json={"status": "fixed", "note": "Striker plate adjusted"})
    s = next(
        x
        for x in (await pm.post(base, json={"status": "verified"})).json()["file"]["snags"]
        if x["id"] == s["id"]
    )
    assert s["status"] == "verified"  # waits for the customer
    assert (
        await pse.post(f"{base}/customer", json={"response": "disputed"})
    ).status_code == 422  # what is disputed?
    s = next(
        x
        for x in (
            await pse.post(
                f"{base}/customer", json={"response": "disputed", "note": "Still sticks"}
            )
        ).json()["file"]["snags"]
        if x["id"] == s["id"]
    )
    assert (
        s["status"] == "open"
        and s["reopen_reason"] == "Customer dispute: Still sticks"
        and s["reopened_count"] == 1
    )
    await site.post(base, json={"status": "fixed", "note": "Hinge replaced"})
    await pm.post(base, json={"status": "verified"})
    s = next(
        x
        for x in (
            await pse.post(f"{base}/customer", json={"response": "accepted", "note": "Fine now"})
        ).json()["file"]["snags"]
        if x["id"] == s["id"]
    )
    assert (s["status"], s["customer_response"]) == ("closed", "accepted")


async def test_inspection_condition_allows_minor_open_snags(login_as, case):
    await opened(login_as, case)
    pse, _ = await login_as(Role.postsales_exec)
    site, site_user = await login_as(Role.site)

    def cond(st):
        return next(c for c in st["file"]["gate"]["conditions"] if c["key"] == "inspection")["met"]

    assert (
        await pse.post(
            f"/api/post-sales/cases/{case}/possession/inspections",
            json={"conducted_on": (TODAY + timedelta(days=1)).isoformat()},
        )
    ).status_code == 422
    assert (
        await pse.post(
            f"/api/post-sales/cases/{case}/possession/inspections",
            json={"report_shared_on": TODAY.isoformat()},
        )
    ).status_code == 422  # how?
    st = (
        await pse.post(
            f"/api/post-sales/cases/{case}/possession/inspections",
            json={"conducted_on": TODAY.isoformat(), "attendees": "Anita, Pooja, Sam"},
        )
    ).json()
    assert cond(st) is True
    await snag(
        pse,
        case,
        site_user.id,
        source="customer",
        severity="minor",
        inspection_id=st["file"]["inspections"][0]["id"],
    )
    assert (
        cond((await pse.get(f"/api/post-sales/cases/{case}/possession")).json()) is True
    )  # a minor snag can stay open
    await snag(
        pse,
        case,
        site_user.id,
        source="customer",
        severity="critical",
        description="Exposed wiring",
    )
    assert cond((await pse.get(f"/api/post-sales/cases/{case}/possession")).json()) is False


async def test_status_dates_and_completing_the_handover(login_as, db, case):
    admin = await opened(login_as, case)
    pid = await project_id(db, case)
    await admin.put(f"/api/projects/{pid}/legal", json=LEGAL)
    await admin.put(f"/api/projects/{pid}/bank", json=BANK)
    db.add(Agreement(case_id=case, status=AgreementStatus.registered, registration_no="HVL-1"))
    await db.commit()
    st = (await admin.get(f"/api/post-sales/cases/{case}/possession")).json()["file"]
    assert st["possession_status"]["status"] == "readiness_in_progress"
    assert {p["key"] for p in st["possession_status"]["pending"]} >= {
        "financial_clearance_pending",
        "inspection_pending",
    }
    assert st["dates"]["legally_eligible"] is None
    pse, _ = await login_as(Role.postsales_exec)
    r = await pse.post(
        f"/api/post-sales/cases/{case}/possession/handover/complete",
        json={"actual_possession_on": TODAY.isoformat()},
    )
    assert r.status_code == 422 and "gate isn't open" in r.text
    crm, _ = await login_as(Role.crm_manager)
    st = (
        await crm.post(
            f"/api/post-sales/cases/{case}/possession/exception",
            json={"reason": "MD approved possession for testing", "scope": ALL},
        )
    ).json()["file"]
    assert (
        st["possession_status"]["status"] == "ready_for_possession"
        and st["dates"]["legally_eligible"] == TODAY.isoformat()
    )
    r = await pse.post(
        f"/api/post-sales/cases/{case}/possession/handover/complete",
        json={"actual_possession_on": TODAY.isoformat()},
    )
    assert r.status_code == 422 and "appointment first" in r.text
    await pse.post(
        f"/api/post-sales/cases/{case}/appointments",
        json={
            "kind": "possession",
            "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    st = (await pse.get(f"/api/post-sales/cases/{case}/possession")).json()["file"]
    assert st["possession_status"]["status"] == "appointment_scheduled"
    r = await pse.post(
        f"/api/post-sales/cases/{case}/possession/handover/complete",
        json={"actual_possession_on": TODAY.isoformat()},
    )
    assert (
        r.status_code == 422
        and "customer identity verified" in r.text
        and "signed handover checklist" in r.text
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
            files={"file": ("cl.pdf", PDF + b"signed", "application/pdf")},
        )
    ).json()["documents"][0]
    await pse.put(
        f"/api/post-sales/cases/{case}/possession/handover",
        json={
            "items": {
                "identity_verified": True,
                "authorisation": "Self",
                "keys_count": 3,
                "access_cards": 2,
                "parking": "B1-14",
                "customer_acknowledged": True,
                "signed_checklist_document_id": doc["id"],
            }
        },
    )
    st = (
        await pse.post(
            f"/api/post-sales/cases/{case}/possession/handover/complete",
            json={"actual_possession_on": TODAY.isoformat()},
        )
    ).json()["file"]
    assert (
        st["possession_status"]["status"] == "handover_completed"
        and st["dates"]["actual_possession"] == TODAY.isoformat()
        and st["handover"]["parking"] == "B1-14"
    )
    assert (
        await pse.put(
            f"/api/post-sales/cases/{case}/possession/handover", json={"items": {"keys_count": 4}}
        )
    ).status_code == 422  # completed: locked
    _ = PostSalesCase


async def test_registration_details(login_as, db, case):
    db.add(Agreement(case_id=case, status=AgreementStatus.registered, registration_no="HVL-2"))
    await db.commit()
    legal, _ = await login_as(Role.legal)
    base = f"/api/post-sales/cases/{case}/agreement/registration"
    assert (
        "how the deed was delivered"
        in (await legal.put(base, json={"delivered_on": TODAY.isoformat()})).text
    )
    assert (
        "Record the delivery before"
        in (await legal.put(base, json={"customer_acknowledged": True})).text
    )
    assert (
        "Note why the original is held"
        in (await legal.put(base, json={"original_custody": "lender"})).text
    )
    r = await legal.put(
        base,
        json={
            "signatories": "Anita Desai; Rahul Test for Avnee Estates",
            "documents": {"PAN copies": True, "Photographs": True},
            "receipt_ref": "SRO-RCT-778",
            "original_custody": "lender",
            "custody_note": "HDFC holds the original until the loan is repaid",
            "delivered_on": TODAY.isoformat(),
            "delivered_via": "lender",
            "customer_acknowledged": True,
        },
    )
    reg = r.json()["agreement"]["registration"]
    assert (
        r.status_code == 200
        and reg["original_custody"] == "lender"
        and reg["customer_acknowledged"] is True
        and reg["by"]
    )
