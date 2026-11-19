from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import PostSalesCase, Role, Unit
from tests import test_ledger
from tests.test_demands import LEGAL, approved_ledger, project_id
from tests.test_ledger import TODAY

case = test_ledger.case
PROFILE = {
    "ownership_type": "individual",
    "legal_name": "Anita Desai",
    "pan": "ABCPD1234E",
    "correspondence_address": "Flat 4, Baner Road, Pune",
    "consent_data": True,
    "co_applicants": [],
}
PDF = b"%PDF-1.4\n%registered agreement\n"


async def ready(login_as, db, case_id):
    """Everything the agreement needs: KYC approved, ledger approved, 10% received, unit areas, legal details."""
    fin, chk = await approved_ledger(login_as, case_id)
    rid = (await chk.get(f"/api/post-sales/cases/{case_id}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case_id}/receipts/{rid}/confirm")  # Rs 3,22,500 = 10%
    pse, _ = await login_as(Role.postsales_exec)
    await pse.put(f"/api/post-sales/cases/{case_id}/profile", json=PROFILE)
    c = await db.get(PostSalesCase, case_id)
    c.onboarding_status = "approved"  # KYC approval itself is covered in test_postsales
    unit = await db.get(Unit, c.booking.unit_id)
    unit.carpet_sqft, unit.builtup_sqft = 141.87, 205.71
    await db.commit()
    admin, _ = await login_as(Role.admin)
    await admin.put(f"/api/projects/{await project_id(db, case_id)}/legal", json=LEGAL)
    return pse, fin, chk


async def st(c, case_id):
    return (await c.get(f"/api/post-sales/cases/{case_id}/agreement")).json()


async def drafted(login_as, db, case_id):
    pse, fin, chk = await ready(login_as, db, case_id)
    await pse.post(f"/api/post-sales/cases/{case_id}/agreement/initiate")
    await pse.post(f"/api/post-sales/cases/{case_id}/agreement/verify")
    legal, legal_user = await login_as(Role.legal)
    assert (
        await legal.post(f"/api/post-sales/cases/{case_id}/agreement/generate")
    ).status_code == 200
    await legal.post(f"/api/post-sales/cases/{case_id}/agreement/submit")
    return pse, legal, chk


async def test_conditions_gate_the_start(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    r = await pse.post(f"/api/post-sales/cases/{case}/agreement/initiate")
    assert (
        r.status_code == 422
        and "KYC approved" in r.text
        and "Ledger approved" in r.text
        and "10% of the agreement value" in r.text
    )
    await ready(login_as, db, case)
    s = await st(pse, case)
    assert all(c["ok"] for c in s["conditions"]) and s["can"]["initiate"]
    r = await pse.post(f"/api/post-sales/cases/{case}/agreement/initiate")
    assert (
        r.status_code == 201
        and r.json()["agreement"]["status"] == "initiated"
        and r.json()["agreement"]["agreement_no"].startswith("AGR-")
    )
    assert (await pse.post(f"/api/post-sales/cases/{case}/agreement/initiate")).status_code == 409


async def test_discrepancies_block_verification(login_as, db, case):
    pse, fin, chk = await ready(login_as, db, case)
    await pse.post(f"/api/post-sales/cases/{case}/agreement/initiate")
    unit = await db.scalar(select(Unit).limit(1))
    unit.builtup_sqft = None
    await db.commit()
    r = await pse.post(f"/api/post-sales/cases/{case}/agreement/verify")
    assert r.status_code == 422 and "Unit areas recorded" in r.text
    unit.builtup_sqft = 205.71
    await db.commit()
    s = (await pse.post(f"/api/post-sales/cases/{case}/agreement/verify")).json()
    assert s["agreement"]["status"] == "data_verified" and all(c["ok"] for c in s["checks"])


async def test_the_draft_is_filled_from_the_case(login_as, db, case):
    await drafted(login_as, db, case)
    pse, _ = await login_as(Role.postsales_exec)
    d = (await st(pse, case))["agreement"]["draft"]
    assert (
        d["version"] == 1
        and d["developer"]["name"] == LEGAL["developer_legal_name"]
        and d["purchasers"][0]["pan"] == "ABCPD1234E"
    )
    assert (
        d["unit"]["saleable_sqft"] == 205.71
        and d["agreement_value"] == 3_225_000
        and len(d["schedule"]) == 17
    )
    assert (
        f"Unit {d['unit']['unit_no']} in Habitat" in d["clauses"][0]
        and "Rs 32,25,000" in d["clauses"][0]
        and d["placeholder_clauses"] is True
    )


async def test_legal_and_finance_both_approve_never_the_drafter(login_as, db, case):
    pse, legal, chk = await drafted(login_as, db, case)
    assert (
        await legal.post(f"/api/post-sales/cases/{case}/agreement/approve")
    ).status_code == 403  # drafted it
    assert (
        await pse.post(f"/api/post-sales/cases/{case}/agreement/share", json={"method": "email"})
    ).status_code == 422  # no approvals yet
    legal2, _ = await login_as(Role.legal)
    s = (await legal2.post(f"/api/post-sales/cases/{case}/agreement/approve")).json()
    assert s["agreement"]["legal_approved_by"] and not s["agreement"]["finance_approved_by"]
    assert (await legal2.post(f"/api/post-sales/cases/{case}/agreement/approve")).status_code == 422
    s = (await chk.post(f"/api/post-sales/cases/{case}/agreement/approve")).json()
    assert (
        s["agreement"]["finance_approved_by"] and s["can"]["share"] is False
    )  # approvers don't share; post-sales does
    # Changes requested -> a new version; approvals start over
    s = (
        await chk.post(
            f"/api/post-sales/cases/{case}/agreement/request-changes",
            json={"reason": "Add the parking clause"},
        )
    ).json()
    assert (
        s["agreement"]["status"] == "changes_requested"
        and s["agreement"]["changes_note"] == "Add the parking clause"
    )
    s = (await legal.post(f"/api/post-sales/cases/{case}/agreement/generate")).json()
    assert (
        s["agreement"]["version"] == 2
        and s["agreement"]["legal_approved_by"] is None
        and s["agreement"]["finance_approved_by"] is None
    )


async def test_an_admin_cannot_give_both_approvals(login_as, db, case):
    await drafted(login_as, db, case)
    admin, _ = await login_as(Role.admin)
    await admin.post(f"/api/post-sales/cases/{case}/agreement/approve")  # counts as legal
    r = await admin.post(f"/api/post-sales/cases/{case}/agreement/approve")
    assert r.status_code in (403, 422)


async def full_review(login_as, db, case_id):
    pse, legal, chk = await drafted(login_as, db, case_id)
    legal2, _ = await login_as(Role.legal)
    await legal2.post(f"/api/post-sales/cases/{case_id}/agreement/approve")
    await chk.post(f"/api/post-sales/cases/{case_id}/agreement/approve")
    await pse.post(f"/api/post-sales/cases/{case_id}/agreement/share", json={"method": "email"})
    s = (await pse.post(f"/api/post-sales/cases/{case_id}/agreement/customer-accepted")).json()
    return pse, legal, s


async def test_customer_review_then_execution_and_registration(login_as, db, case):
    pse, legal, s = await full_review(login_as, db, case)
    a = s["agreement"]
    assert (
        a["status"] == "execution_prep"
        and a["share_method"] == "email"
        and a["stamp_duty_amount"] == 225_800
        and a["registration_fee_amount"] == 30_000
    )
    reg = {
        "executed_on": TODAY.isoformat(),
        "registration_no": "HVL-1-12345-2026",
        "registered_on": TODAY.isoformat(),
        "sro_office": "Haveli 1",
    }
    r = await legal.post(f"/api/post-sales/cases/{case}/agreement/register", json=reg)
    assert (
        r.status_code == 422
        and "stamp duty paid" in r.text
        and "registration appointment" in r.text
    )
    when = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    await pse.put(
        f"/api/post-sales/cases/{case}/agreement/execution",
        json={
            "stamp_duty_amount": 225_800,
            "stamp_duty_paid_on": TODAY.isoformat(),
            "stamp_duty_ref": "GRAS-1",
            "registration_fee_amount": 30_000,
            "registration_fee_paid_on": TODAY.isoformat(),
            "appointment_at": when,
            "sro_office": "Haveli 1",
            "id_docs_ready": True,
        },
    )
    bad = {**reg, "registered_on": (TODAY - timedelta(days=1)).isoformat()}
    assert (
        await legal.post(f"/api/post-sales/cases/{case}/agreement/register", json=bad)
    ).status_code == 422
    s = (await legal.post(f"/api/post-sales/cases/{case}/agreement/register", json=reg)).json()
    assert (
        s["agreement"]["status"] == "registered"
        and s["agreement"]["registration_no"] == "HVL-1-12345-2026"
    )


async def test_final_upload_goes_to_folder_03_and_completes_on_release(login_as, db, case):
    pse, legal, _ = await full_review(login_as, db, case)
    await pse.put(
        f"/api/post-sales/cases/{case}/agreement/execution",
        json={
            "stamp_duty_paid_on": TODAY.isoformat(),
            "registration_fee_paid_on": TODAY.isoformat(),
            "appointment_at": datetime.now(UTC).isoformat(),
            "id_docs_ready": True,
        },
    )
    await legal.post(
        f"/api/post-sales/cases/{case}/agreement/register",
        json={
            "executed_on": TODAY.isoformat(),
            "registration_no": "HVL-1-777-2026",
            "registered_on": TODAY.isoformat(),
        },
    )
    r = await legal.post(
        f"/api/post-sales/cases/{case}/agreement/final",
        files={"file": ("signed.pdf", PDF, "application/pdf")},
    )
    a = r.json()["agreement"]
    assert a["status"] == "final_uploaded" and a["final_document"]["approval"] == "under_approval"
    folder = (await pse.get(f"/api/post-sales/cases/{case}/documents")).json()
    doc = next(d for d in folder["documents"] if d["id"] == a["final_document"]["id"])
    assert (doc["category"], doc["doc_number"], doc["linked_ref"]) == (
        "agreements",
        "HVL-1-777-2026",
        a["agreement_no"],
    )
    crm, _ = await login_as(Role.crm_manager)
    await crm.post(f"/api/post-sales/documents/{doc['id']}/approve")
    await crm.post(f"/api/post-sales/documents/{doc['id']}/release")
    assert (await st(pse, case))["agreement"]["status"] == "completed"


async def test_permissions_and_cancelling(login_as, db, case):
    pse, fin, chk = await ready(login_as, db, case)
    await pse.post(f"/api/post-sales/cases/{case}/agreement/initiate")
    await pse.post(f"/api/post-sales/cases/{case}/agreement/verify")
    assert (
        await pse.post(f"/api/post-sales/cases/{case}/agreement/generate")
    ).status_code == 403  # drafting is for legal / CRM manager
    ex, _ = await login_as(Role.executive)
    assert (await ex.get(f"/api/post-sales/cases/{case}/agreement")).status_code == 403
    assert (
        await pse.post(
            f"/api/post-sales/cases/{case}/agreement/cancel",
            json={"reason": "Customer wants changes"},
        )
    ).status_code == 403
    crm, _ = await login_as(Role.crm_manager)
    s = (
        await crm.post(
            f"/api/post-sales/cases/{case}/agreement/cancel",
            json={"reason": "Wrong unit in the template"},
        )
    ).json()
    assert (
        s["agreement"] is None and s["history"][0]["cancel_reason"] == "Wrong unit in the template"
    )
    assert (
        await pse.post(f"/api/post-sales/cases/{case}/agreement/initiate")
    ).status_code == 201  # a fresh start is possible


@pytest.mark.parametrize("pct,ok", [(10, True), (20, False)])
async def test_the_paid_threshold_is_set_per_project(login_as, db, case, pct, ok):
    await ready(login_as, db, case)
    admin, _ = await login_as(Role.admin)
    pid = await project_id(db, case)
    t = (await admin.get(f"/api/projects/{pid}/cost-sheet")).json()
    assert (
        await admin.put(
            f"/api/projects/{pid}/cost-sheet", json={**t, "agreement_min_paid_pct": pct}
        )
    ).status_code == 200
    pse, _ = await login_as(Role.postsales_exec)
    assert (
        (await pse.post(f"/api/post-sales/cases/{case}/agreement/initiate")).status_code == 201
    ) is ok


@pytest.mark.parametrize(
    "n,txt",
    [
        (999, "999"),
        (1000, "1,000"),
        (100000, "1,00,000"),
        (3225000, "32,25,000"),
        (125000000, "12,50,00,000"),
    ],
)
def test_amounts_use_indian_grouping(n, txt):
    from app.services.agreements import inr

    assert inr(n) == txt
