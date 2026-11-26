import re
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import PostSalesCase, Role
from app.models.audit import AuditLog
from app.models.inventory import Building, Unit
from app.models.ledger import Ledger
from app.models.portal import PortalSession
from app.models.postsales import CustomerProfile
from app.models.ticket import Ticket
from app.services import comms
from tests import test_ledger
from tests.test_demands import approved_ledger
from tests.test_ledger import PAID, PRICE, TODAY
from tests.test_payments import rec

case = test_ledger.case
PDF = b"%PDF-1.4\nportal test"


@pytest.fixture
def portal_on(monkeypatch):
    s = comms.get_settings()
    monkeypatch.setattr(s, "portal_enabled", True)
    outbox = []
    monkeypatch.setitem(
        comms.SENDERS, "email", lambda to, subj, body: outbox.append((to, subj, body))
    )
    return outbox


async def customer(db, case_id, email="anita@example.com", portal=True):
    p = await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == case_id))
    p.legal_name, p.email, p.mobile = (
        "Anita Desai" if email.startswith("anita") else "Rohan Mehta",
        email,
        "9000000001",
    )
    p.consent_portal_at = datetime.now(UTC) if portal else None
    p.consent_electronic_at = datetime.now(UTC)
    await db.commit()


async def second_case(db, login_as) -> int:
    admin, _ = await login_as(Role.admin)
    b = await db.scalar(select(Building))
    await admin.post(
        f"/api/buildings/{b.id}/generate",
        json={"floor_from": 12, "floor_to": 12, "units_per_floor": 1, "unit_type": "studio"},
    )
    unit_id = await db.scalar(select(Unit.id).order_by(Unit.id.desc()))
    lead = (
        await admin.post(
            "/api/leads", json={"name": "Rohan Mehta", "mobile": "9000000002", "source": "99acres"}
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
    cid = await db.scalar(select(PostSalesCase.id).where(PostSalesCase.booking_id == bk["id"]))
    pse, _ = await login_as(Role.postsales_exec)
    await pse.post(f"/api/post-sales/cases/{cid}/accept")
    return cid


async def sign_in(outbox, email="anita@example.com") -> AsyncClient:
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    await c.post("/api/portal/auth/request", json={"email": email})
    code = re.search(r"\b(\d{6})\b", outbox[-1][2]).group(1)
    r = await c.post("/api/portal/auth/verify", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    return c


async def test_off_by_default_and_needs_https_in_production(case, monkeypatch):
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    assert (await c.get("/api/portal/status")).json()["enabled"] is False
    assert (
        await c.post("/api/portal/auth/request", json={"email": "anita@example.com"})
    ).status_code == 503
    s = comms.get_settings()
    monkeypatch.setattr(s, "portal_enabled", True)
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "cookie_secure", False)
    st = (await c.get("/api/portal/status")).json()
    assert st["enabled"] is False and "HTTPS" in st["reason"]


async def test_sign_in_rules(db, case, portal_on):
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    r1 = (await c.post("/api/portal/auth/request", json={"email": "nobody@example.com"})).json()
    await customer(db, case, portal=False)
    r2 = (await c.post("/api/portal/auth/request", json={"email": "anita@example.com"})).json()
    assert r1 == r2 and portal_on == []  # same answer; no email without portal consent
    await customer(db, case)
    await c.post("/api/portal/auth/request", json={"email": "ANITA@example.com "})
    assert len(portal_on) == 1 and portal_on[0][0] == "anita@example.com"
    code = re.search(r"\b(\d{6})\b", portal_on[0][2]).group(1)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            await c.post(
                "/api/portal/auth/verify", json={"email": "anita@example.com", "code": wrong}
            )
        ).status_code == 400
    assert (
        await c.post("/api/portal/auth/verify", json={"email": "anita@example.com", "code": code})
    ).status_code == 400  # locked after 5 tries
    await c.post("/api/portal/auth/request", json={"email": "anita@example.com"})
    await c.post("/api/portal/auth/request", json={"email": "anita@example.com"})
    await c.post("/api/portal/auth/request", json={"email": "anita@example.com"})
    assert len(portal_on) == 3  # the 4th request in 15 minutes sends nothing
    code = re.search(r"\b(\d{6})\b", portal_on[-1][2]).group(1)
    r = await c.post("/api/portal/auth/verify", json={"email": "anita@example.com", "code": code})
    cookie = r.headers["set-cookie"].lower()
    assert (
        r.status_code == 200
        and "httponly" in cookie
        and "samesite=strict" in cookie
        and "path=/api/portal" in cookie
    )
    me = (await c.get("/api/portal/me")).json()
    assert me["name"] == "Anita Desai" and me["units"][0]["case_id"] == case
    assert (
        await c.post("/api/portal/auth/verify", json={"email": "anita@example.com", "code": code})
    ).status_code == 400  # a code works once


async def test_customers_only_see_their_own_case(db, login_as, case, portal_on):
    other = await second_case(db, login_as)
    await customer(db, case)
    await customer(db, other, email="rohan@example.com")
    site, _ = await login_as(Role.site)
    d = (
        await site.post(
            f"/api/post-sales/cases/{case}/documents",
            data={
                "category": "possession",
                "doc_type": "Allotment letter",
                "title": "Allotment letter",
            },
            files={"file": ("a.pdf", PDF, "application/pdf")},
        )
    ).json()["documents"][0]
    rohan = await sign_in(portal_on, "rohan@example.com")
    for path in (
        "dashboard",
        "payments",
        "documents",
        "property",
        "agreement",
        "notifications",
        "profile",
        "help",
        f"documents/{d['id']}/file",
    ):
        assert (await rohan.get(f"/api/portal/cases/{case}/{path}")).status_code == 404, path
    assert (await rohan.get(f"/api/portal/cases/{other}/dashboard")).status_code == 200
    assert (
        await rohan.get("/api/users/me")
    ).status_code == 401  # a portal session is not a staff session
    staff, _ = await login_as(Role.admin)
    assert (
        await staff.get(f"/api/portal/cases/{case}/dashboard")
    ).status_code == 401  # and a staff session is not a portal session


async def test_sessions_idle_logout_and_sign_out_elsewhere(db, case, portal_on):
    await customer(db, case)
    a = await sign_in(portal_on)
    b = await sign_in(portal_on)
    assert len((await a.get("/api/portal/sessions")).json()) == 2
    assert (await a.post("/api/portal/sessions/sign-out-others")).json()["signed_out"] == 1
    assert (await b.get("/api/portal/me")).status_code == 401
    for s in await db.scalars(select(PortalSession).where(PortalSession.revoked_at.is_(None))):
        s.last_seen_at = datetime.now(UTC) - timedelta(minutes=61)
    await db.commit()
    assert (await a.get("/api/portal/me")).status_code == 401  # idle for over an hour
    c = await sign_in(portal_on)
    await c.post("/api/portal/auth/logout")
    assert (await c.get("/api/portal/me")).status_code == 401


async def test_payment_statuses_in_plain_language(db, login_as, case, portal_on):
    fin, chk = await approved_ledger(login_as, case)
    await customer(db, case)
    c = await sign_in(portal_on)
    p = (await c.get(f"/api/portal/cases/{case}/payments")).json()
    assert (
        p["stages"][0]["status"] == "Payment received - reconciliation pending"
        and p["pending_reconciliation"] == PAID
    )
    assert (
        p["stages"][1]["status"] == "Not yet demanded"
        and p["headline"] == "Payment received - reconciliation pending"
    )
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    p = (await c.get(f"/api/portal/cases/{case}/payments")).json()
    gap = p["stages"][0][
        "outstanding"
    ]  # the GST on the booking amount is still unpaid, and due today
    assert (
        gap > 0
        and p["stages"][0]["status"] == "Payment due"
        and p["headline"] == "Payment due"
        and p["total_paid"] == PAID
    )
    rid2 = max(
        x["id"]
        for x in (
            await fin.post(f"/api/post-sales/cases/{case}/receipts", json=rec(gap, ref="UTR-GST"))
        ).json()["receipts"]
    )
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid2}/confirm")
    p = (await c.get(f"/api/portal/cases/{case}/payments")).json()
    assert (
        p["stages"][0]["status"] == "Payment confirmed"
        and p["headline"] == "No payment currently due"
    )
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case))
    await db.refresh(ledger)
    plinth = next(i for i in ledger.schedule if i.name == "Plinth")
    plinth.demanded_on, plinth.due_date = TODAY - timedelta(days=20), TODAY + timedelta(days=5)
    await db.commit()
    p = (await c.get(f"/api/portal/cases/{case}/payments")).json()
    assert (
        p["headline"] == "Upcoming payment" and p["next_due"]["stage"] == "Plinth"
    )  # not overdue before the due date
    plinth.due_date = TODAY
    await db.commit()
    assert (await c.get(f"/api/portal/cases/{case}/payments")).json()["headline"] == "Payment due"
    plinth.due_date = TODAY - timedelta(days=1)
    await db.commit()
    assert (await c.get(f"/api/portal/cases/{case}/payments")).json()[
        "headline"
    ] == "Overdue payment"
    pse, _ = await login_as(Role.postsales_exec)
    await pse.post(
        f"/api/post-sales/cases/{case}/tickets",
        data={
            "category": "demand",
            "title": "Plinth amount query",
            "description": "Customer questions the GST",
        },
    )
    assert (await c.get(f"/api/portal/cases/{case}/payments")).json()[
        "headline"
    ] == "Payment under clarification"
    d = (await c.get(f"/api/portal/cases/{case}/dashboard")).json()
    assert (
        d["payments"]["next_due"]["status"] == "Payment under clarification"
        and d["pending_actions"]
    )


async def test_documents_secure_downloads_and_change_requests(db, login_as, case, portal_on):
    await customer(db, case)
    site, _ = await login_as(Role.site)
    crm, _ = await login_as(Role.crm_manager)

    def up(title, cat):
        return site.post(
            f"/api/post-sales/cases/{case}/documents",
            data={"category": cat, "doc_type": "Letter", "title": title},
            files={"file": (f"{title}.pdf", PDF + title.encode(), "application/pdf")},
        )

    shared = next(
        x
        for x in (await up("Possession letter", "possession")).json()["documents"]
        if x["title"] == "Possession letter"
    )
    internal = next(
        x
        for x in (await up("Internal inspection notes", "possession")).json()["documents"]
        if x["title"] == "Internal inspection notes"
    )
    admin, _ = await login_as(Role.admin)
    await admin.post(f"/api/post-sales/documents/{shared['id']}/approve")
    r = await crm.post(f"/api/post-sales/documents/{shared['id']}/release")
    assert r.status_code == 200, r.text
    c = await sign_in(portal_on)
    docs = (await c.get(f"/api/portal/cases/{case}/documents")).json()
    assert [x["title"] for x in docs] == ["Possession letter"]
    f = await c.get(f"/api/portal/cases/{case}/documents/{shared['id']}/file")
    assert (
        f.status_code == 200
        and f.content.startswith(b"%PDF")
        and "no-store" in f.headers["cache-control"]
    )
    assert (
        await c.get(f"/api/portal/cases/{case}/documents/{internal['id']}/file")
    ).status_code == 404
    assert await db.scalar(
        select(AuditLog.id).where(AuditLog.action == "portal.document_downloaded")
    )
    before = (await c.get(f"/api/portal/cases/{case}/profile")).json()["mobile"]
    r = (
        await c.post(
            f"/api/portal/cases/{case}/profile/change-request",
            json={"field": "mobile", "new_value": "9876543210", "note": "New number"},
        )
    ).json()
    t = await db.scalar(select(Ticket).where(Ticket.subcategory == "Profile change request"))
    assert (
        r["request_no"] == f"TKT-{t.id:05d}"
        and t.channel == "portal"
        and "9876543210" in t.description
    )
    assert (await c.get(f"/api/portal/cases/{case}/profile")).json()[
        "mobile"
    ] == before  # not applied directly
