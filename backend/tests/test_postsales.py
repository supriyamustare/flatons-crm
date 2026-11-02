from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AuditLog, KycDocument, Notification, PostSalesCase, Role, Unit
from tests.conftest import new_project

TODAY = datetime.now(UTC).date().isoformat()
STAGES = [{"name": "Booking", "pct": 10}, {"name": "Rest", "pct": 90}]


def png(n: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + bytes([n]) * 64  # different content each time


@pytest.fixture
async def booked(db, login_as):
    """A project with a payment plan, and a booking by Ravi (sales executive)."""
    admin, _ = await login_as(Role.admin)
    project = await new_project(db, "Habitat")
    project.cost_sheet = {"stages": STAGES}
    await db.commit()
    b = (await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "Habitat"})).json()
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": 2, "floor_to": 2, "units_per_floor": 2, "unit_type": "studio"},
    )
    unit_id = await db.scalar(select(Unit.id).order_by(Unit.id))
    ravi, ravi_user = await login_as(Role.executive)
    _, psx = await login_as(Role.postsales_exec)
    lead = (
        await ravi.post(
            "/api/leads", json={"name": "Anita Desai", "mobile": "9876543210", "source": "99acres"}
        )
    ).json()["lead"]
    bk = (
        await ravi.post(
            "/api/bookings",
            json={
                "lead_id": lead["id"],
                "unit_id": unit_id,
                "booking_date": TODAY,
                "agreed_price": 4_000_000,
                "booking_amount": 400_000,
                "customer": {"customer_address": "Baner, Pune"},
            },
        )
    ).json()
    case_id = await db.scalar(select(PostSalesCase.id).where(PostSalesCase.booking_id == bk["id"]))
    return {
        "ravi": ravi,
        "ravi_user": ravi_user,
        "booking": bk,
        "case_id": case_id,
        "project": project,
        "lead": lead,
        "psx_id": psx.id,
    }


async def accepted(login_as, booked):
    pse, user = await login_as(Role.postsales_exec)
    r = await pse.post(f"/api/post-sales/cases/{booked['case_id']}/accept")
    assert r.status_code == 200, r.text
    return pse, user


async def test_booking_creates_a_case_filled_from_the_booking(login_as, db, booked):
    case = await db.get(PostSalesCase, booked["case_id"])
    assert case.status.value == "handover_pending" and case.onboarding_status.value == "not_started"
    note = await db.scalar(
        select(Notification).where(
            Notification.type == "handover", Notification.user_id == booked["psx_id"]
        )
    )
    assert note and note.link == f"/post-sales/{case.id}"
    crm, _ = await login_as(Role.crm_manager)
    d = (await crm.get(f"/api/post-sales/cases/{case.id}")).json()
    assert (
        d["customer"],
        d["profile"]["legal_name"],
        d["profile"]["mobile"],
        d["profile"]["correspondence_address"],
    ) == ("Anita Desai", "Anita Desai", "+919876543210", "Baner, Pune")
    assert all(i["ok"] for i in d["handover"] if i["required"])


async def test_post_sales_roles_never_see_pre_sales_leads(login_as, booked):
    for role in (
        Role.postsales_exec,
        Role.crm_manager,
        Role.finance,
        Role.legal,
        Role.site,
        Role.auditor,
    ):
        c, _ = await login_as(role)
        assert (await c.post("/api/leads/search", json={})).status_code == 403, role
        assert (await c.get(f"/api/leads/{booked['lead']['id']}")).status_code == 403, role
        assert (await c.get(f"/api/post-sales/cases/{booked['case_id']}")).status_code == 200, role
    # Sales see the case's status on their booking, but not the case itself (KYC, profile)
    assert (
        await booked["ravi"].get(f"/api/post-sales/cases/{booked['case_id']}")
    ).status_code == 403
    s = (await booked["ravi"].get(f"/api/post-sales/by-booking/{booked['booking']['id']}")).json()
    assert s["status"] == "handover_pending" and "profile" not in s


async def test_return_to_sales_resend_and_accept(login_as, db, booked):
    pse, user = await login_as(Role.postsales_exec)
    cid = booked["case_id"]
    assert (
        await pse.post(f"/api/post-sales/cases/{cid}/return", json={"reason": "x"})
    ).status_code == 422
    r = await pse.post(
        f"/api/post-sales/cases/{cid}/return", json={"reason": "Customer email missing"}
    )
    assert (
        r.json()["status"] == "returned_to_sales"
        and r.json()["returned_reason"] == "Customer email missing"
    )
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == booked["ravi_user"].id, Notification.type == "handover_returned"
        )
    )
    assert (await pse.post(f"/api/post-sales/cases/{cid}/accept")).status_code == 422
    assert (await booked["ravi"].post(f"/api/post-sales/cases/{cid}/resend")).json() == {
        "status": "handover_pending"
    }
    r = await pse.post(f"/api/post-sales/cases/{cid}/accept")
    assert r.json()["status"] == "accepted" and r.json()["onboarding_status"] == "documents_pending"
    assert r.json()["owner"]["id"] == user.id
    auditor, _ = await login_as(Role.auditor)
    assert (
        await auditor.post(f"/api/post-sales/cases/{cid}/assign", json={"owner_id": user.id})
    ).status_code == 403
    assert [h["action"] for h in r.json()["history"]] == [
        "created",
        "returned_to_sales",
        "resent_by_sales",
        "accepted",
    ]


async def test_handover_needs_a_payment_plan(login_as, db, booked):
    booked["project"].cost_sheet = None
    await db.commit()
    pse, _ = await login_as(Role.postsales_exec)
    r = await pse.post(f"/api/post-sales/cases/{booked['case_id']}/accept")
    assert r.status_code == 422 and "Payment plan" in r.text


PROFILE = {
    "ownership_type": "joint",
    "legal_name": "Anita Desai",
    "pan": "abcde1234f",
    "ownership_pct": 50,
    "correspondence_address": "Flat 4, Baner Road, Pune",
    "consent_data": True,
    "consent_portal": True,
    "co_applicants": [
        {"name": "Rohan Desai", "relation": "Spouse", "pan": "PQRST6789K", "ownership_pct": 50}
    ],
}


async def test_customer_master_rules(login_as, booked):
    pse, _ = await login_as(Role.postsales_exec)
    cid = booked["case_id"]
    assert (
        await pse.put(f"/api/post-sales/cases/{cid}/profile", json=PROFILE)
    ).status_code == 422  # not accepted yet
    await pse.post(f"/api/post-sales/cases/{cid}/accept")
    r = await pse.put(f"/api/post-sales/cases/{cid}/profile", json=PROFILE)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (
        d["profile"]["pan"] == "ABCDE1234F"
        and d["profile"]["consent_data_at"]
        and not d["profile"]["consent_electronic_at"]
    )
    assert [c["name"] for c in d["co_applicants"]] == ["Rohan Desai"] and d[
        "profile_problems"
    ] == []
    assert len(d["requirements"]) == 8  # 4 each for two applicants
    bad = await pse.put(
        f"/api/post-sales/cases/{cid}/profile", json={**PROFILE, "ownership_pct": 60}
    )
    assert "Ownership shares must add up to 100%" in bad.json()["profile_problems"]
    assert (
        await pse.put(f"/api/post-sales/cases/{cid}/profile", json={**PROFILE, "pan": "12345"})
    ).status_code == 422
    company = await pse.put(
        f"/api/post-sales/cases/{cid}/profile",
        json={**PROFILE, "ownership_type": "company", "co_applicants": []},
    )
    assert {r["key"] for r in company.json()["requirements"]} >= {
        "entity_pan",
        "registration",
        "authority",
    }
    assert "Entity name" in company.json()["profile_problems"]


async def upload(c, cid, doc_type, n, co_applicant_id=None):
    data = {"doc_type": doc_type} | (
        {"co_applicant_id": str(co_applicant_id)} if co_applicant_id else {}
    )
    return await c.post(
        f"/api/post-sales/cases/{cid}/kyc",
        data=data,
        files={"file": (f"{doc_type}.png", png(n), "image/png")},
    )


async def test_kyc_review_and_onboarding_approval(login_as, db, booked):
    pse, _ = await accepted(login_as, booked)
    cid = booked["case_id"]
    individual = {
        **PROFILE,
        "ownership_type": "individual",
        "ownership_pct": None,
        "co_applicants": [],
    }
    await pse.put(f"/api/post-sales/cases/{cid}/profile", json=individual)
    r = await upload(pse, cid, "pan", 1)
    assert r.status_code == 201 and r.json()["onboarding_status"] == "documents_pending"
    assert (await upload(pse, cid, "pan", 1)).status_code == 409  # the same file again
    await upload(pse, cid, "aadhaar", 2)  # covers identity and address
    r = await upload(pse, cid, "photo", 3)
    assert r.json()["onboarding_status"] == "under_review"  # every requirement now has a document
    docs = {d["doc_type"]: d["id"] for d in r.json()["documents"]}

    assert (
        await pse.post(f"/api/post-sales/kyc/{docs['pan']}/verify")
    ).status_code == 403  # uploader can't verify
    reviewer, _ = await login_as(Role.crm_manager)
    r = await reviewer.post(
        f"/api/post-sales/kyc/{docs['photo']}/reject", json={"reason": "Photo is blurred"}
    )
    assert (
        r.json()["onboarding_status"] == "clarification_required"
        and r.json()["clarification_reason"] == "Photo is blurred"
    )
    r = await upload(pse, cid, "photo", 4)  # replacement
    assert r.json()["onboarding_status"] == "under_review"
    old = await db.get(KycDocument, docs["photo"])
    assert old.status.value == "rejected" or old.status.value == "superseded"
    new_photo = next(
        d["id"]
        for d in r.json()["documents"]
        if d["doc_type"] == "photo" and d["status"] == "pending"
    )
    early = await reviewer.post(
        f"/api/post-sales/cases/{cid}/onboarding", json={"action": "approve"}
    )
    assert early.status_code == 422 and "Can't approve yet" in early.text
    for doc_id in (docs["pan"], docs["aadhaar"], new_photo):
        assert (await reviewer.post(f"/api/post-sales/kyc/{doc_id}/verify")).status_code == 200
    r = await reviewer.post(f"/api/post-sales/cases/{cid}/onboarding", json={"action": "approve"})
    assert (
        r.status_code == 200
        and r.json()["onboarding_status"] == "approved"
        and r.json()["kyc_done"] == r.json()["kyc_total"] == 4
    )
    # Changing the buyer's identity after approval sends it back for review
    r = await pse.put(
        f"/api/post-sales/cases/{cid}/profile", json={**individual, "pan": "ZZZZZ9999Z"}
    )
    assert r.json()["onboarding_status"] == "under_review"


async def test_kyc_files_are_restricted_and_viewing_is_logged(login_as, db, booked):
    pse, _ = await accepted(login_as, booked)
    doc_id = (await upload(pse, booked["case_id"], "pan", 9)).json()["documents"][0]["id"]
    for role, code in (
        (Role.legal, 200),
        (Role.auditor, 200),
        (Role.finance, 403),
        (Role.site, 403),
        (Role.manager, 403),
        (Role.executive, 403),
    ):
        c, _ = await login_as(role)
        assert (await c.get(f"/api/post-sales/kyc/{doc_id}/file")).status_code == code, role
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "kyc.viewed"))


async def test_cancelling_the_booking_cancels_the_case(login_as, db, booked):
    mgr, _ = await login_as(Role.manager)
    await mgr.post(
        f"/api/bookings/{booked['booking']['id']}/cancel", json={"reason": "Customer withdrew"}
    )
    db.expire_all()
    assert (await db.get(PostSalesCase, booked["case_id"])).status.value == "cancelled"


async def test_case_list_counts_and_new_roles_can_be_created(login_as, booked):
    admin, _ = await login_as(Role.admin)
    page = (await admin.get("/api/post-sales/cases")).json()
    assert page["total"] == 1 and page["counts"]["status:handover_pending"] == 1
    r = await admin.post(
        "/api/users",
        json={
            "email": "fin@flatons.com",
            "full_name": "Fin Approver",
            "role": "finance_approver",
            "password": "team-pass-123",
        },
    )
    assert r.status_code == 201 and r.json()["role"] == "finance_approver"
