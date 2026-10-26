import re

import pytest
from sqlalchemy import select

from app.models import AuditLog, Lead, Role
from app.schemas.common import normalize_mobile
from tests.conftest import new_project

BASE = {"name": "Anita Desai", "mobile": "98765 43210", "source": "99acres"}


async def create(c, **overrides):
    resp = await c.post("/api/leads", json={**BASE, **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---- Phone normalisation -------------------------------------------------


@pytest.mark.parametrize(
    "typed", ["9876543210", "98765 43210", "+91 98765-43210", "09876543210", "919876543210"]
)
def test_indian_mobile_formats_are_normalised(typed):
    assert normalize_mobile(typed) == "+919876543210"


@pytest.mark.parametrize("typed", ["12345", "5876543210", "+91 12345 67890", "abc"])
def test_invalid_mobiles_are_rejected(typed):
    with pytest.raises(ValueError):
        normalize_mobile(typed)


def test_international_numbers_are_kept():
    assert normalize_mobile("+44 20 7946 0958") == "+442079460958"


# ---- Create --------------------------------------------------------------


async def test_executive_creates_lead_assigned_to_themselves(login_as):
    c, executive = await login_as(Role.executive)

    body = await create(c)

    lead = body["lead"]
    assert re.fullmatch(r"LEAD-\d{8}-0001", lead["lead_code"])
    assert lead["mobile"] == "+919876543210"
    assert lead["status"] == "new"
    assert lead["assigned_to"]["id"] == executive.id
    assert body["duplicates"] == []


async def test_lead_codes_increase_within_a_day(login_as):
    c, _ = await login_as(Role.executive)
    first = (await create(c))["lead"]["lead_code"]
    second = (await create(c, mobile="9876500000"))["lead"]["lead_code"]
    assert first.endswith("-0001") and second.endswith("-0002")
    assert first[:13] == second[:13]


async def test_executive_cannot_assign_lead_to_someone_else(login_as, make_user):
    c, executive = await login_as(Role.executive)
    other = await make_user(Role.executive)
    lead = (await create(c, assigned_to_id=other.id))["lead"]
    assert lead["assigned_to"]["id"] == executive.id


async def test_manager_can_create_unassigned_or_assigned_lead(login_as, make_user):
    c, _ = await login_as(Role.manager)
    executive = await make_user(Role.executive)
    assert (await create(c))["lead"]["assigned_to"] is None
    lead = (await create(c, mobile="9000000001", assigned_to_id=executive.id))["lead"]
    assert lead["assigned_to"]["id"] == executive.id


async def test_docs_staff_cannot_create_leads(login_as):
    c, _ = await login_as(Role.docs)
    assert (await c.post("/api/leads", json=BASE)).status_code == 403


@pytest.mark.parametrize(
    "bad",
    [
        {"mobile": "12345"},
        {"name": ""},
        {"source": "tv"},
        {"budget_min": 9_000_000, "budget_max": 5_000_000},
        {"email": "not-an-email"},
        {"remarks": "<img src=x onerror=alert(1)>"},
    ],
)
async def test_invalid_leads_are_rejected(login_as, bad):
    c, _ = await login_as(Role.executive)
    assert (await c.post("/api/leads", json={**BASE, **bad})).status_code == 422


async def test_remarks_may_use_less_than_sign(login_as):
    c, _ = await login_as(Role.executive)
    lead = (await create(c, remarks="Budget < 80L, prefers east facing"))["lead"]
    assert lead["remarks"] == "Budget < 80L, prefers east facing"


async def test_creation_is_recorded_in_timeline(login_as):
    c, _ = await login_as(Role.executive)
    lead = (await create(c))["lead"]
    detail = (await c.get(f"/api/leads/{lead['id']}")).json()
    assert [a["type"] for a in detail["activities"]] == ["created"]


# ---- Duplicates ----------------------------------------------------------


async def test_duplicate_mobile_warns_but_still_creates(login_as):
    """Sprint 2 'done when': duplicate warning appears on matching phone."""
    c, _ = await login_as(Role.executive)
    first = (await create(c))["lead"]

    body = await create(c, name="Anita D.", mobile="+91-98765-43210")

    assert body["lead"]["id"] != first["id"]
    [dup] = body["duplicates"]
    assert dup["lead_code"] == first["lead_code"]
    assert dup["matched_on"] == ["mobile"]
    assert dup["can_view"] is True


async def test_duplicate_matches_alternate_number_and_email(login_as):
    c, _ = await login_as(Role.manager)
    await create(c, alt_mobile="9123456780", email="Anita@Mail.com")

    by_alt = await create(c, mobile="9123456780")
    by_email = await create(c, mobile="9000000009", email="anita@mail.com")

    assert by_alt["duplicates"][0]["matched_on"] == ["mobile"]
    assert by_email["duplicates"][0]["matched_on"] == ["email"]


async def test_duplicate_check_endpoint_hides_other_executives_leads(login_as):
    exec_a, _ = await login_as(Role.executive)
    exec_b, _ = await login_as(Role.executive)
    await create(exec_a)

    resp = await exec_b.post("/api/leads/duplicates", json={"mobile": "9876543210"})

    [dup] = resp.json()
    assert dup["can_view"] is False  # B is warned but can't open A's lead


async def test_deleted_leads_are_not_duplicates(login_as):
    admin, _ = await login_as(Role.admin)
    lead = (await create(admin))["lead"]
    await admin.delete(f"/api/leads/{lead['id']}")
    assert (await create(admin))["duplicates"] == []


# ---- Visibility ----------------------------------------------------------


async def test_executive_only_sees_own_leads(login_as):
    exec_a, _ = await login_as(Role.executive)
    exec_b, _ = await login_as(Role.executive)
    lead_a = (await create(exec_a))["lead"]
    await create(exec_b, mobile="9000000002")

    page = (await exec_a.post("/api/leads/search", json={})).json()

    assert page["total"] == 1 and page["items"][0]["id"] == lead_a["id"]
    assert (await exec_b.get(f"/api/leads/{lead_a['id']}")).status_code == 404
    assert (
        await exec_b.patch(f"/api/leads/{lead_a['id']}", json={"city": "Pune"})
    ).status_code == 404


@pytest.mark.parametrize("role", [Role.manager, Role.admin, Role.docs])
async def test_managers_admins_and_docs_see_all_leads(login_as, role):
    exec_a, _ = await login_as(Role.executive)
    await create(exec_a)
    c, _ = await login_as(role)
    assert (await c.post("/api/leads/search", json={})).json()["total"] == 1


async def test_docs_staff_get_read_only_access(login_as):
    exec_a, _ = await login_as(Role.executive)
    lead = (await create(exec_a))["lead"]
    docs, _ = await login_as(Role.docs)

    detail = await docs.get(f"/api/leads/{lead['id']}")
    assert detail.status_code == 200 and detail.json()["can_edit"] is False
    assert (await docs.patch(f"/api/leads/{lead['id']}", json={"city": "Pune"})).status_code == 403
    assert (
        await docs.post(f"/api/leads/{lead['id']}/notes", json={"note": "hi"})
    ).status_code == 403


# ---- Search & filters ----------------------------------------------------


async def test_search_by_name_phone_and_lead_code(login_as):
    c, _ = await login_as(Role.manager)
    anita = (await create(c))["lead"]
    await create(c, name="Rahul Mehta", mobile="9988776655", source="walk_in")

    async def q(term):
        return [
            i["name"] for i in (await c.post("/api/leads/search", json={"q": term})).json()["items"]
        ]

    assert await q("anita") == ["Anita Desai"]
    assert await q("43210") == ["Anita Desai"]
    assert await q("98765 4") == ["Anita Desai"]
    assert await q(anita["lead_code"]) == ["Anita Desai"]
    assert await q("100%") == []  # wildcards are treated literally


async def test_filters_and_pagination(login_as, make_user, db):
    c, _ = await login_as(Role.manager)
    executive = await make_user(Role.executive)
    project = await new_project(db, "Green Meadows")
    await db.commit()
    for i in range(5):
        await create(
            c,
            mobile=f"900000001{i}",
            source="walk_in" if i % 2 else "website",
            project_id=project.id if i < 2 else None,
            assigned_to_id=executive.id if i == 0 else None,
        )

    async def total(**f):
        return (await c.post("/api/leads/search", json=f)).json()["total"]

    assert await total(sources=["walk_in"]) == 2
    assert await total(project_id=project.id) == 2
    assert await total(assigned_to_id=executive.id) == 1
    assert await total(unassigned=True) == 4
    assert await total(statuses=["lost"]) == 0
    page2 = (
        await c.post(
            "/api/leads/search", json={"page": 2, "page_size": 2, "sort": "name", "order": "asc"}
        )
    ).json()
    assert page2["total"] == 5 and len(page2["items"]) == 2


# ---- Status rules ----------------------------------------------------------


async def test_status_change_is_logged_in_timeline_and_audit(login_as, db):
    """Sprint 2 'done when': update status and see it in the activity timeline."""
    c, executive = await login_as(Role.executive)
    lead = (await create(c))["lead"]

    resp = await c.post(
        f"/api/leads/{lead['id']}/status", json={"status": "contacted", "note": "Spoke to her"}
    )

    assert resp.status_code == 200
    detail = resp.json()
    assert detail["status"] == "contacted"
    latest = detail["activities"][0]
    assert latest["type"] == "status_change"
    assert latest["details"] == {"from": "new", "to": "contacted"}
    assert latest["note"] == "Spoke to her"
    assert latest["actor"]["id"] == executive.id
    audit = await db.scalar(select(AuditLog).where(AuditLog.action == "lead.status_change"))
    assert audit.entity_id == str(lead["id"])


@pytest.mark.parametrize("status", ["lost", "junk"])
async def test_lost_and_junk_require_a_reason(login_as, status):
    c, _ = await login_as(Role.executive)
    lead = (await create(c))["lead"]
    url = f"/api/leads/{lead['id']}/status"

    assert (await c.post(url, json={"status": status})).status_code == 422
    assert (await c.post(url, json={"status": status, "reason": "  "})).status_code == 422
    ok = await c.post(url, json={"status": status, "reason": "Bought elsewhere"})
    assert ok.status_code == 200 and ok.json()["lost_reason"] == "Bought elsewhere"


async def test_reopening_a_lost_lead_clears_the_reason(login_as):
    c, _ = await login_as(Role.executive)
    lead = (await create(c))["lead"]
    url = f"/api/leads/{lead['id']}/status"
    await c.post(url, json={"status": "lost", "reason": "Budget mismatch"})
    reopened = (await c.post(url, json={"status": "follow_up"})).json()
    assert reopened["lost_reason"] is None


async def test_only_managers_can_mark_booked(login_as):
    exec_c, _ = await login_as(Role.executive)
    lead = (await create(exec_c))["lead"]
    url = f"/api/leads/{lead['id']}/status"
    assert (await exec_c.post(url, json={"status": "booked"})).status_code == 422

    mgr, _ = await login_as(Role.manager)
    assert (await mgr.post(url, json={"status": "booked"})).status_code == 200
    assert (await exec_c.post(url, json={"status": "negotiation"})).status_code == 422


async def test_same_status_is_rejected(login_as):
    c, _ = await login_as(Role.executive)
    lead = (await create(c))["lead"]
    assert (
        await c.post(f"/api/leads/{lead['id']}/status", json={"status": "new"})
    ).status_code == 422


# ---- Update, notes, assignment, delete ------------------------------------


async def test_update_records_changes_without_copying_contact_details(login_as):
    c, _ = await login_as(Role.executive)
    lead = (await create(c))["lead"]

    resp = await c.patch(
        f"/api/leads/{lead['id']}",
        json={"city": "Pune", "mobile": "9000011111", "budget_max": 9_000_000},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mobile"] == "+919000011111"
    changes = body["activities"][0]["details"]["changes"]
    assert changes["city"] == {"from": None, "to": "Pune"}
    assert changes["mobile"] == "changed"  # number itself is not copied into the log


async def test_update_rejects_budget_range_against_existing_value(login_as):
    c, _ = await login_as(Role.executive)
    lead = (await create(c, budget_max=5_000_000))["lead"]
    resp = await c.patch(f"/api/leads/{lead['id']}", json={"budget_min": 6_000_000})
    assert resp.status_code == 422


async def test_note_is_added_to_timeline(login_as):
    c, _ = await login_as(Role.executive)
    lead = (await create(c))["lead"]
    detail = (
        await c.post(f"/api/leads/{lead['id']}/notes", json={"note": "Wants a park-facing flat"})
    ).json()
    assert detail["activities"][0]["type"] == "note"
    assert detail["activities"][0]["note"] == "Wants a park-facing flat"


async def test_manager_reassigns_lead_and_it_moves_between_executives(login_as, db):
    mgr, _ = await login_as(Role.manager)
    exec_a, a = await login_as(Role.executive)
    exec_b, b = await login_as(Role.executive)
    lead = (await create(exec_a))["lead"]

    resp = await mgr.post(f"/api/leads/{lead['id']}/assign", json={"assigned_to_id": b.id})

    assert resp.status_code == 200
    assert resp.json()["activities"][0]["details"]["to"]["id"] == b.id
    assert (await exec_a.get(f"/api/leads/{lead['id']}")).status_code == 404
    assert (await exec_b.get(f"/api/leads/{lead['id']}")).status_code == 200
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "lead.assign")) is not None


async def test_executive_cannot_reassign(login_as, make_user):
    c, _ = await login_as(Role.executive)
    other = await make_user(Role.executive)
    lead = (await create(c))["lead"]
    resp = await c.post(f"/api/leads/{lead['id']}/assign", json={"assigned_to_id": other.id})
    assert resp.status_code == 403


async def test_cannot_assign_to_admin_docs_or_inactive_user(login_as, make_user):
    mgr, _ = await login_as(Role.manager)
    lead = (await create(mgr))["lead"]
    url = f"/api/leads/{lead['id']}/assign"
    for target in [
        await make_user(Role.docs),
        await make_user(Role.admin),
        await make_user(Role.executive, is_active=False),
    ]:
        assert (await mgr.post(url, json={"assigned_to_id": target.id})).status_code == 422


async def test_assignable_users_list(login_as, make_user):
    mgr, _ = await login_as(Role.manager)
    await make_user(Role.executive)
    await make_user(Role.docs)
    roles = {u["role"] for u in (await mgr.get("/api/users/assignable")).json()}
    assert roles == {"manager", "executive"}
    exec_c, _ = await login_as(Role.executive)
    assert (await exec_c.get("/api/users/assignable")).status_code == 403


async def test_only_admin_can_delete_and_it_is_soft(login_as, db):
    mgr, _ = await login_as(Role.manager)
    lead = (await create(mgr))["lead"]
    assert (await mgr.delete(f"/api/leads/{lead['id']}")).status_code == 403

    admin, _ = await login_as(Role.admin)
    assert (await admin.delete(f"/api/leads/{lead['id']}")).status_code == 204
    assert (await admin.get(f"/api/leads/{lead['id']}")).status_code == 404
    assert (await admin.post("/api/leads/search", json={})).json()["total"] == 0
    still_there = await db.scalar(select(Lead.deleted_at).where(Lead.id == lead["id"]))
    assert still_there is not None


# ---- Projects ---------------------------------------------------------------


async def test_projects_admin_manages_everyone_reads(login_as):
    admin, _ = await login_as(Role.admin)
    exec_c, _ = await login_as(Role.executive)

    created = await admin.post(
        "/api/projects", json={"name": "Green Meadows", "developer_name": "Skyline Developers"}
    )
    assert created.status_code == 201
    assert (
        await admin.post(
            "/api/projects", json={"name": "green meadows", "developer_name": "Skyline Developers"}
        )
    ).status_code == 409
    assert (
        await exec_c.post("/api/projects", json={"name": "X", "project_type": "resale"})
    ).status_code == 403
    assert [p["name"] for p in (await exec_c.get("/api/projects")).json()] == ["Green Meadows"]

    pid = created.json()["id"]
    await admin.patch(f"/api/projects/{pid}", json={"is_active": False})
    assert (await exec_c.get("/api/projects")).json() == []
    assert (await exec_c.post("/api/leads", json={**BASE, "project_id": pid})).status_code == 422
