import hashlib
import hmac
import json

import pytest
from sqlalchemy import select, text

from app.models import InboundEvent, Integration, Lead, LeadActivity, Notification, Role
from app.tasks import inbound as fb_task
from tests.conftest import new_project


async def connect(admin, kind="website", **kw):
    body = {"name": kw.pop("name", f"{kind} connection"), "kind": kind, **kw}
    r = await admin.post("/api/integrations", json=body)
    assert r.status_code == 201, r.text
    return r.json()["integration"], r.json()["secret"]


async def send(client, integration, secret, payload, **kw):
    return await client.post(
        integration["path"], json=payload, headers={"X-Flatons-Key": secret}, **kw
    )


# ---------------------------------------------------------------- website & portals


async def test_website_enquiry_becomes_unassigned_lead_in_inbox(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    project = await new_project(db, "Green Meadows")
    conn, secret = await connect(admin, default_project_id=project.id)

    r = await send(
        client,
        conn,
        secret,
        {
            "name": "Anita Desai",
            "phone": "98765 43210",
            "email": "Anita@Example.com",
            "message": "Want a 2 BHK",
            "id": "web-1",
        },
    )

    assert r.status_code == 200 and r.json()["status"] == "created"
    lead = await db.get(Lead, r.json()["lead_id"])
    assert (lead.name, lead.mobile, lead.email, lead.source.value) == (
        "Anita Desai",
        "+919876543210",
        "anita@example.com",
        "website",
    )
    assert (
        lead.assigned_to_id is None and lead.created_by_id is None and lead.project_id == project.id
    )
    assert lead.remarks == "Want a 2 BHK"
    created = await db.scalar(select(LeadActivity).where(LeadActivity.lead_id == lead.id))
    assert created.type == "created" and created.details["via"] == "website connection"
    inbox = (await admin.get("/api/inbox")).json()
    assert inbox["count"] == 1 and inbox["items"][0]["name"] == "Anita Desai"
    assert inbox["items"][0]["message"] == "Want a 2 BHK"


async def test_portal_style_fields_query_key_form_post_and_batches(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(admin, kind="99acres")
    # Portal-style names, key in the URL
    r = await client.post(
        f"{conn['path']}?key={secret}",
        json={
            "customer_name": "Rahul Patil",
            "contact_number": "+91-91234-56780",
            "query": "Site visit Sunday",
            "property_name": "Green Meadows 2BHK",
            "query_id": "Q1",
        },
    )
    assert r.json()["status"] == "created"
    lead = await db.get(Lead, r.json()["lead_id"])
    assert lead.source.value == "99acres" and lead.sub_source == "Green Meadows 2BHK"
    # Form-encoded body
    r = await client.post(
        f"{conn['path']}?key={secret}", data={"name": "Priya", "mobile": "9988776655"}
    )
    assert r.json()["status"] == "created"
    # Several in one request
    r = await send(
        client,
        conn,
        secret,
        {"leads": [{"name": "A", "mobile": "9000000001"}, {"name": "B", "mobile": "9000000002"}]},
    )
    assert [x["status"] for x in r.json()["results"]] == ["created", "created"]
    assert (await db.get(Integration, conn["id"])).received_count == 4


@pytest.mark.parametrize("how", ["no key", "wrong key", "unknown connection"])
async def test_wrong_or_missing_key_is_refused(login_as, client, db, how):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(admin)
    path = "/api/inbound/9999" if how == "unknown connection" else conn["path"]
    headers = {} if how == "no key" else {"X-Flatons-Key": "nope" if how == "wrong key" else secret}
    r = await client.post(path, json={"name": "X", "mobile": "9876543210"}, headers=headers)
    assert r.status_code == 401
    assert await db.scalar(select(Lead.id)) is None


async def test_switched_off_connection_refuses(login_as, client):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(admin)
    await admin.patch(f"/api/integrations/{conn['id']}", json={"is_active": False})
    assert (
        await send(client, conn, secret, {"name": "X", "mobile": "9876543210"})
    ).status_code == 403


async def test_repeat_enquiry_is_added_to_existing_lead_and_owner_alerted(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    ravi, ravi_user = await login_as(Role.executive)
    lead = (
        await ravi.post(
            "/api/leads", json={"name": "Anita", "mobile": "9876543210", "source": "walk_in"}
        )
    ).json()["lead"]
    conn, secret = await connect(admin, kind="magicbricks")

    r = await send(
        client,
        conn,
        secret,
        {"name": "Anita D", "mobile": "+91 98765-43210", "message": "Still interested"},
    )

    assert r.json() == {"status": "merged", "lead_id": lead["id"], "detail": None}
    assert await db.scalar(text("SELECT count(*) FROM leads")) == 1
    enquiry = await db.scalar(select(LeadActivity).where(LeadActivity.type == "enquiry"))
    assert enquiry.note == "Still interested" and enquiry.details["via"] == "magicbricks connection"
    note = await db.scalar(select(Notification).where(Notification.type == "repeat_enquiry"))
    assert note.user_id == ravi_user.id and note.link == f"/leads/{lead['id']}"


async def test_repeat_enquiry_for_unassigned_lead_alerts_managers(login_as, client, db):
    admin, admin_user = await login_as(Role.admin)
    _, manager = await login_as(Role.manager)
    conn, secret = await connect(admin)
    await send(client, conn, secret, {"name": "A", "mobile": "9876543210"})
    await send(client, conn, secret, {"name": "A", "mobile": "9876543210", "message": "again"})
    alerted = set(
        await db.scalars(select(Notification.user_id).where(Notification.type == "repeat_enquiry"))
    )
    assert alerted == {admin_user.id, manager.id}


async def test_platform_retry_is_recorded_once(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(admin)
    payload = {"name": "A", "mobile": "9876543210", "lead_id": "abc-1"}
    first = await send(client, conn, secret, payload)
    again = await send(client, conn, secret, payload)
    assert first.json()["lead_id"] == again.json()["lead_id"]
    assert await db.scalar(text("SELECT count(*) FROM inbound_events")) == 1
    assert await db.scalar(text("SELECT count(*) FROM lead_activities")) == 1


async def test_no_valid_phone_is_logged_not_created(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(admin)
    r = await send(client, conn, secret, {"name": "No phone", "email": "x@example.com"})
    assert (
        r.status_code == 200 and r.json()["status"] == "rejected"
    )  # 200 so the platform doesn't retry forever
    assert "phone" in r.json()["detail"]
    assert await db.scalar(select(Lead.id)) is None
    events = (await admin.get(f"/api/integrations/{conn['id']}/events")).json()
    assert events[0]["status"] == "rejected" and events[0]["payload"]["name"] == "No phone"


async def test_test_mode_creates_nothing(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(admin)
    r = await send(
        client, conn, secret, {"name": "Test", "mobile": "9876543210"}, params={"test": "true"}
    )
    assert r.json()["status"] == "test" and "+919876543210" in r.json()["detail"]
    assert await db.scalar(select(Lead.id)) is None


async def test_html_is_stripped_and_oversized_requests_refused(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(admin)
    r = await send(
        client,
        conn,
        secret,
        {"name": "<script>x</script>Anita", "mobile": "9876543210", "message": "<b>hi</b>"},
    )
    lead = await db.get(Lead, r.json()["lead_id"])
    assert "<" not in lead.name and "<" not in lead.remarks
    big = await send(
        client, conn, secret, {"name": "A", "mobile": "9876543210", "message": "x" * 70_000}
    )
    assert big.status_code == 413


# ---------------------------------------------------------------- Google Ads


GOOGLE = {
    "lead_id": "G-1",
    "form_id": 42,
    "is_test": False,
    "user_column_data": [
        {"column_id": "FULL_NAME", "string_value": "Vikram Joshi"},
        {"column_id": "PHONE_NUMBER", "string_value": "+919123456780"},
        {"column_id": "EMAIL", "string_value": "vikram@example.com"},
        {"column_id": "CITY", "string_value": "Pune"},
    ],
}


async def test_google_ads_lead_form(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(admin, kind="google_ads")
    r = await client.post(conn["path"], json={**GOOGLE, "google_key": secret})
    assert r.json()["status"] == "created"
    lead = await db.get(Lead, r.json()["lead_id"])
    assert (lead.name, lead.mobile, lead.city, lead.source.value, lead.sub_source) == (
        "Vikram Joshi",
        "+919123456780",
        "Pune",
        "google_ads",
        "Google form 42",
    )
    stored = await db.scalar(select(InboundEvent.payload))
    assert "google_key" not in stored  # the secret isn't kept in the log
    bad = await client.post(conn["path"], json={**GOOGLE, "lead_id": "G-2", "google_key": "wrong"})
    assert bad.status_code == 401
    test = await client.post(
        conn["path"], json={**GOOGLE, "lead_id": "G-3", "is_test": True, "google_key": secret}
    )
    assert test.json()["status"] == "test"


# ---------------------------------------------------------------- Facebook


FB_APP_SECRET = "fb-app-secret-1234567890"


def signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = hmac.new(FB_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"}


async def test_facebook_lead_ads(login_as, client, db, monkeypatch):
    admin, _ = await login_as(Role.admin)
    conn, secret = await connect(
        admin, kind="facebook", fb_app_secret=FB_APP_SECRET, fb_page_token="EAAG-page-token-xyz"
    )
    assert conn["facebook_ready"] and conn["path"].endswith("/facebook")
    stored = await db.scalar(text("SELECT fb_page_token_enc FROM integrations"))
    assert "EAAG" not in stored  # encrypted at rest

    ok = await client.get(
        conn["path"],
        params={"hub.mode": "subscribe", "hub.verify_token": secret, "hub.challenge": "12345"},
    )
    assert ok.status_code == 200 and ok.text == "12345"
    bad = await client.get(
        conn["path"],
        params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"},
    )
    assert bad.status_code == 401

    queued = []
    monkeypatch.setattr(fb_task.facebook_lead, "delay", lambda event_id: queued.append(event_id))
    body = {
        "object": "page",
        "entry": [
            {"changes": [{"field": "leadgen", "value": {"leadgen_id": "FB-777", "form_id": "F1"}}]}
        ],
    }
    raw, headers = signed(body)
    assert (
        await client.post(
            conn["path"], content=raw, headers={**headers, "X-Hub-Signature-256": "sha256=bad"}
        )
    ).status_code == 401
    r = await client.post(conn["path"], content=raw, headers=headers)
    assert r.json() == {"received": 1} and len(queued) == 1
    again = await client.post(conn["path"], content=raw, headers=headers)  # Facebook re-sends
    assert again.json() == {"received": 0}

    async def fake_fetch(leadgen_id, token):
        assert (leadgen_id, token) == ("FB-777", "EAAG-page-token-xyz")
        return {
            "id": "FB-777",
            "form_id": "F1",
            "field_data": [
                {"name": "full_name", "values": ["Sneha Gupta"]},
                {"name": "phone_number", "values": ["+91 99887 76655"]},
                {"name": "email", "values": ["sneha@example.com"]},
            ],
        }

    monkeypatch.setattr(fb_task, "fetch_facebook_lead_data", fake_fetch)
    assert await fb_task.process_facebook_event(queued[0]) == "created"
    lead = await db.scalar(select(Lead).where(Lead.name == "Sneha Gupta"))
    assert (lead.mobile, lead.source.value, lead.assigned_to_id) == (
        "+919988776655",
        "social",
        None,
    )
    assert (await db.get(Integration, conn["id"])).received_count == 1


# ---------------------------------------------------------------- admin & inbox


async def test_setup_is_admin_only_and_secret_rotates(login_as, client):
    mgr, _ = await login_as(Role.manager)
    assert (await mgr.get("/api/integrations")).status_code == 403
    assert (
        await mgr.post("/api/integrations", json={"name": "x", "kind": "website"})
    ).status_code == 403
    admin, _ = await login_as(Role.admin)
    assert (
        await admin.post("/api/integrations", json={"name": "fb", "kind": "facebook"})
    ).status_code == 422
    conn, old = await connect(admin)
    listed = (await admin.get("/api/integrations")).json()
    assert "secret" not in json.dumps(listed).lower().replace(
        "secret_hash", ""
    )  # never shown again
    new = (await admin.post(f"/api/integrations/{conn['id']}/rotate")).json()["secret"]
    assert (await send(client, conn, old, {"name": "A", "mobile": "9876543210"})).status_code == 401
    assert (await send(client, conn, new, {"name": "A", "mobile": "9876543210"})).status_code == 200


async def test_inbox_is_for_managers_and_assigning_hands_the_lead_over(login_as, client, db):
    admin, _ = await login_as(Role.admin)
    mgr, _ = await login_as(Role.manager)
    ravi, ravi_user = await login_as(Role.executive)
    conn, secret = await connect(admin)
    lead_id = (await send(client, conn, secret, {"name": "Anita", "mobile": "9876543210"})).json()[
        "lead_id"
    ]
    assert (await ravi.get("/api/inbox")).status_code == 403
    assert (await mgr.get("/api/inbox/count")).json() == {"count": 1}

    r = await mgr.post(f"/api/leads/{lead_id}/assign", json={"assigned_to_id": ravi_user.id})

    assert r.status_code == 200
    assert (await mgr.get("/api/inbox/count")).json() == {"count": 0}
    note = await db.scalar(
        select(Notification).where(
            Notification.user_id == ravi_user.id, Notification.type == "lead_assigned"
        )
    )
    assert note.link == f"/leads/{lead_id}"
    assert (await ravi.get(f"/api/leads/{lead_id}")).status_code == 200
