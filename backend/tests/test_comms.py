from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import PostSalesCase, Role
from app.models.comms import CommMessage
from app.models.postsales import CustomerProfile
from app.services import comms
from tests import test_ledger
from tests.test_demands import approved_ledger

case = test_ledger.case
BODY = "Dear {customer},\n\nWe have received Rs {amount} for unit {unit}. Receipt {receipt_no}.\n\n{company}"


async def profile(db, case_id, **kw):
    """Accepting a case already creates the profile; fill in contact details and consent."""
    p = await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == case_id))
    for k, v in {
        "legal_name": "Anita Desai",
        "email": "anita@example.com",
        "mobile": "9000000001",
        "contact_email": True,
        "contact_sms": True,
        "contact_whatsapp": False,
        "consent_electronic_at": datetime.now(UTC),
        **kw,
    }.items():
        setattr(p, k, v)
    await db.commit()
    return p


async def approved(
    login_as,
    event="payment_received",
    channel="email",
    body=BODY,
    subject="Payment received: {receipt_no}",
    mandatory=False,
):
    author, _ = await login_as(Role.crm_manager)
    checker, _ = await login_as(Role.admin)
    r = await author.post(
        "/api/comms/templates",
        json={
            "event": event,
            "channel": channel,
            "subject": subject if channel == "email" else None,
            "body": body,
            "mandatory": mandatory,
        },
    )
    assert r.status_code == 201, r.text
    tid = max(
        t["id"] for t in r.json()["templates"] if t["event"] == event and t["channel"] == channel
    )
    assert (
        await author.post(f"/api/comms/templates/{tid}/approve")
    ).status_code == 403  # never the author
    r = await checker.post(f"/api/comms/templates/{tid}/approve")
    assert r.status_code == 200
    return tid, author, checker


async def test_template_rules_and_versions(login_as):
    crm, _ = await login_as(Role.crm_manager)
    bad = {
        "event": "payment_received",
        "channel": "email",
        "subject": "x",
        "body": "Your receipt: https://crm.example/api/receipt/1 thanks",
    }
    r = await crm.post("/api/comms/templates", json=bad)
    assert r.status_code == 422 and "can't contain links" in r.text
    r = await crm.post(
        "/api/comms/templates", json={**bad, "body": "Dear {customer}, your balance is {balance}."}
    )
    assert r.status_code == 422 and "{balance}" in r.text
    assert (
        "needs a subject"
        in (
            await crm.post(
                "/api/comms/templates",
                json={**bad, "subject": None, "body": "Dear {customer}, thanks."},
            )
        ).text
    )
    tid1, author, checker = await approved(login_as)
    tid2, _, _ = await approved(login_as, body=BODY + "\nThank you.")
    ts = {t["id"]: t for t in (await checker.get("/api/comms/templates")).json()["templates"]}
    assert (ts[tid1]["status"], ts[tid2]["status"], ts[tid2]["version"]) == (
        "retired",
        "approved",
        ts[tid1]["version"] + 1,
    )
    assert (
        await author.put(
            f"/api/comms/templates/{tid2}",
            json={"event": "payment_received", "channel": "email", "subject": "x", "body": BODY},
        )
    ).status_code == 422
    pse, _ = await login_as(Role.postsales_exec)
    assert (await pse.get("/api/comms/templates")).status_code == 403


async def test_emit_renders_and_respects_consent(login_as, db, case):
    c = await db.get(PostSalesCase, case)
    assert (
        await comms.emit(
            db, "payment_received", c, {"amount": 322_500, "receipt_no": "RCT-00001"}, "r1"
        )
        == []
    )  # no approved template yet
    await approved(login_as)
    out = await comms.emit(
        db, "payment_received", c, {"amount": 322_500, "receipt_no": "RCT-00001"}, "r1"
    )
    assert out[0].status == "skipped" and "consent" in out[0].reason  # no profile / consent
    await profile(db, case)
    out = await comms.emit(
        db, "payment_received", c, {"amount": 322_500, "receipt_no": "RCT-00002"}, "r2"
    )
    m = out[0]
    assert (m.status, m.recipient, m.subject) == (
        "queued",
        "anita@example.com",
        "Payment received: RCT-00002",
    )
    assert (
        "Dear Anita Desai" in m.body
        and "Rs 3,22,500" in m.body
        and f"unit {c.booking.unit.unit_no}" in m.body
    )
    assert (
        await comms.emit(db, "payment_received", c, {"amount": 1, "receipt_no": "RCT-00002"}, "r2")
        == []
    )  # same event and reference: no duplicate
    p = await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == case))
    p.contact_email = False
    await db.commit()
    assert (
        await comms.emit(db, "payment_received", c, {"amount": 1, "receipt_no": "RCT-3"}, "r3")
    )[0].reason == "The customer opted out of email"
    await approved(
        login_as,
        event="demand_issued",
        body="Dear {customer}, Rs {amount} for {stage} is due by {due_date}.",
        subject="Demand for {stage}",
        mandatory=True,
    )
    m = (
        await comms.emit(
            db, "demand_issued", c, {"stage": "Plinth", "amount": 100, "due_date": "1 Dec"}, "d1"
        )
    )[0]
    assert m.status == "queued"  # mandatory notices still go
    await approved(
        login_as,
        event="demand_issued",
        channel="whatsapp",
        body="Rs {amount} for {stage} due {due_date}.",
    )
    wa = next(
        x
        for x in await comms.emit(
            db, "demand_issued", c, {"stage": "Plinth", "amount": 100, "due_date": "1 Dec"}, "d2"
        )
        if x.channel == "whatsapp"
    )
    assert wa.status == "skipped" and "WhatsApp" in wa.reason


async def test_delivery_held_sent_retried_failed(login_as, db, case, monkeypatch):
    await profile(db, case)
    await approved(login_as)
    c = await db.get(PostSalesCase, case)
    await comms.emit(db, "payment_received", c, {"amount": 5, "receipt_no": "RCT-9"}, "x1")
    await db.commit()
    assert (await comms.dispatch(db))["held"] == 1  # email not set up
    await db.commit()
    m = await db.scalar(select(CommMessage))
    assert m.status == "held" and "isn't set up" in m.reason
    sent = []
    s = comms.get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "Flatons <crm@example.com>")
    monkeypatch.setitem(comms.SENDERS, "email", lambda to, subj, body: sent.append((to, subj)))
    assert (await comms.dispatch(db))["sent"] == 1 and sent == [
        ("anita@example.com", "Payment received: RCT-9")
    ]
    await db.commit()  # the scheduled job commits after each run
    await db.refresh(m)
    assert m.status == "sent" and m.sent_at is not None

    def broken(to, subj, body):
        raise ConnectionRefusedError("SMTP server refused the connection")

    monkeypatch.setitem(comms.SENDERS, "email", broken)
    await comms.emit(db, "payment_received", c, {"amount": 6, "receipt_no": "RCT-10"}, "x2")
    await db.commit()
    m2 = await db.scalar(
        select(CommMessage).where(CommMessage.dedupe_key.like("payment_received:x2%"))
    )
    t = datetime.now(UTC)
    for minutes in (0, 6, 40, 200):  # first try, then the 5 min, 30 min and 2 h retries
        await comms.dispatch(db, t + timedelta(minutes=minutes))
        await db.commit()
    await db.refresh(m2)
    assert (m2.status, m2.attempts) == ("failed", 4) and "refused" in m2.reason
    crm, _ = await login_as(Role.crm_manager)
    assert (await crm.post(f"/api/comms/messages/{m2.id}/retry")).json()["status"] == "queued"


async def test_real_triggers_and_case_history(login_as, db, case):
    await profile(db, case)
    await approved(login_as)
    await approved(
        login_as,
        event="complaint_created",
        body="Dear {customer}, we registered {ticket_no}: {title}.",
        subject="Request {ticket_no}",
    )
    fin, chk = await approved_ledger(login_as, case)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    pse, _ = await login_as(Role.postsales_exec)
    t = (
        await pse.post(
            f"/api/post-sales/cases/{case}/tickets",
            data={
                "category": "receipt",
                "title": "Need a copy",
                "description": "Customer wants a receipt copy",
            },
        )
    ).json()
    h = (await pse.get(f"/api/post-sales/cases/{case}/communications")).json()
    events = {m["event"]: m for m in h["messages"]}
    assert events["payment_received"]["subject"] == f"Payment received: RCT-{rid:05d}"
    assert t["ticket_no"] in events["complaint_created"]["body"]
    assert h["preferences"]["contact_email"] is True and h["channels"]["email"]
    ex, _ = await login_as(Role.executive)
    assert (await ex.get(f"/api/post-sales/cases/{case}/communications")).status_code == 403
