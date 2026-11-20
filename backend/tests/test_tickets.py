from datetime import timedelta

from sqlalchemy import select

from app.models import Notification, Role
from app.models.ticket import Ticket
from app.services.tickets import now
from tests import test_ledger

case = test_ledger.case
PNG = b"\x89PNG\r\n\x1a\n"


async def raise_(c, case_id, **form):
    files = form.pop("attachments", None)
    data = {
        "category": "defect",
        "title": "Seepage in bathroom wall",
        "description": "Water seeping near the shower since last week",
        "priority": "high",
        **form,
    }
    return await c.post(f"/api/post-sales/cases/{case_id}/tickets", data=data, files=files)


async def test_raising_sets_team_targets_and_notifies(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    _, crm = await login_as(Role.crm_manager)
    r = await raise_(
        pse,
        case,
        priority="urgent",
        attachments=[("attachments", ("wall.png", PNG + b"\x01" * 40, "image/png"))],
    )
    t = r.json()
    assert (
        r.status_code == 201
        and t["ticket_no"].startswith("TKT-")
        and (t["team"], t["status"], len(t["attachments"])) == ("after_sales", "raised", 1)
    )
    row = await db.get(Ticket, t["id"])
    assert row.response_due_at - row.created_at <= timedelta(
        hours=2, seconds=5
    ) and row.resolution_due_at - row.created_at <= timedelta(hours=24, seconds=5)
    assert (await raise_(pse, case, category="payment")).json()["team"] == "finance"
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == crm.id, Notification.type == "ticket_raised"
        )
    )
    aud, _ = await login_as(Role.auditor)
    assert (await aud.get(f"/api/tickets/{t['id']}")).status_code == 200 and (
        await raise_(aud, case)
    ).status_code == 403
    ex, _ = await login_as(Role.executive)
    assert (await ex.get("/api/tickets")).status_code == 403


async def test_workflow_order_and_waiting_needs_a_note(login_as, case):
    pse, me = await login_as(Role.postsales_exec)
    t = (await raise_(pse, case)).json()
    assert (
        await pse.post(f"/api/tickets/{t['id']}/status", json={"status": "in_progress"})
    ).status_code == 422  # acknowledge first
    t = (
        await pse.post(
            f"/api/tickets/{t['id']}/acknowledge",
            json={"text": "We've noted the seepage; a technician will visit."},
        )
    ).json()
    assert (
        t["status"] == "acknowledged"
        and t["owner"]["id"] == me.id
        and t["sla"]["first_response_at"]
    )
    assert (
        await pse.post(f"/api/tickets/{t['id']}/status", json={"status": "waiting_external"})
    ).status_code == 422  # say who
    t = (await pse.post(f"/api/tickets/{t['id']}/status", json={"status": "in_progress"})).json()
    assert t["status"] == "in_progress"


async def test_waiting_for_the_customer_pauses_the_sla(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    t = (await raise_(pse, case)).json()
    await pse.post(f"/api/tickets/{t['id']}/acknowledge", json={"text": "Noted."})
    await pse.post(
        f"/api/tickets/{t['id']}/status",
        json={"status": "waiting_customer", "note": "Asked for photos of the wall"},
    )
    row = await db.get(Ticket, t["id"])
    due_before = row.resolution_due_at
    row.paused_since = now() - timedelta(hours=3)  # three hours waiting
    await db.commit()
    paused = (await pse.get(f"/api/tickets/{t['id']}")).json()["sla"]
    assert paused["paused"] is True and paused["paused_hours_customer"] == 3.0
    t = (await pse.post(f"/api/tickets/{t['id']}/status", json={"status": "in_progress"})).json()
    await db.refresh(row)
    moved = (row.resolution_due_at - due_before).total_seconds()
    assert (
        3 * 3600 - 5 <= moved <= 3 * 3600 + 5
        and t["sla"]["paused"] is False
        and row.paused_seconds_customer >= 3 * 3600 - 5
    )


async def test_notes_stay_internal_messages_are_the_customer_log(login_as, case):
    pse, _ = await login_as(Role.postsales_exec)
    t = (await raise_(pse, case)).json()
    await pse.post(
        f"/api/tickets/{t['id']}/notes", json={"text": "Contractor says it's a plumbing joint"}
    )
    t = (
        await pse.post(
            f"/api/tickets/{t['id']}/messages",
            json={"direction": "out", "text": "We'll visit on Monday", "channel": "whatsapp"},
        )
    ).json()
    kinds = {e["kind"]: e["internal"] for e in t["timeline"]}
    assert kinds["note"] is True and kinds["message_out"] is False
    assert (
        t["status"] == "acknowledged" and t["sla"]["first_response_at"]
    )  # a reply is a first response


async def test_closing_rules_and_customer_confirmation(login_as, case):
    pse, _ = await login_as(Role.postsales_exec)
    t = (await raise_(pse, case)).json()
    tid = t["id"]
    await pse.post(f"/api/tickets/{tid}/acknowledge", json={"text": "Noted."})
    r = await pse.post(f"/api/tickets/{tid}/close", json={"closure_reason": "resolved"})
    assert r.status_code == 422 and "Propose the resolution" in r.text
    await pse.post(f"/api/tickets/{tid}/propose", json={"text": "Joint resealed; wall repainted"})
    r = await pse.post(f"/api/tickets/{tid}/close", json={"closure_reason": "resolved"})
    assert r.status_code == 422 and "needs the customer's confirmation" in r.text  # defects need it
    assert (
        await pse.post(f"/api/tickets/{tid}/confirmation", json={"confirmed": False})
    ).status_code == 422  # what's still wrong?
    t = (
        await pse.post(
            f"/api/tickets/{tid}/confirmation",
            json={"confirmed": False, "comment": "Still damp in the corner"},
        )
    ).json()
    assert t["status"] == "in_progress"
    await pse.post(
        f"/api/tickets/{tid}/propose", json={"text": "Corner treated with waterproofing"}
    )
    await pse.post(
        f"/api/tickets/{tid}/confirmation",
        json={"confirmed": True, "csat": 4, "comment": "Fixed, thanks"},
    )
    t = (await pse.post(f"/api/tickets/{tid}/close", json={"closure_reason": "resolved"})).json()
    assert (t["status"], t["closure_reason"], t["csat"]) == ("closed", "resolved", 4)
    doc = (
        await raise_(pse, case, category="document", title="Need my receipt PDF", priority="low")
    ).json()
    await pse.post(f"/api/tickets/{doc['id']}/acknowledge", json={"text": "Sending it."})
    await pse.post(f"/api/tickets/{doc['id']}/propose", json={"text": "Emailed the statement"})
    assert (
        await pse.post(f"/api/tickets/{doc['id']}/close", json={"closure_reason": "resolved"})
    ).status_code == 200  # no confirmation needed
    dup = (await raise_(pse, case, category="payment")).json()
    assert (
        await pse.post(f"/api/tickets/{dup['id']}/close", json={"closure_reason": "duplicate"})
    ).status_code == 422  # needs a note
    assert (
        await pse.post(
            f"/api/tickets/{dup['id']}/close",
            json={"closure_reason": "duplicate", "note": "Same as TKT-00001"},
        )
    ).json()["status"] == "closed"


async def test_reopening_within_the_period_or_by_a_crm_manager(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    t = (await raise_(pse, case, category="payment")).json()
    await pse.post(
        f"/api/tickets/{t['id']}/close", json={"closure_reason": "duplicate", "note": "Duplicate"}
    )
    t = (
        await pse.post(
            f"/api/tickets/{t['id']}/reopen", json={"reason": "Not a duplicate after all"}
        )
    ).json()
    assert t["status"] == "in_progress" and t["reopened_count"] == 1
    reopened = next(e for e in t["timeline"] if e["kind"] == "reopened")
    assert reopened["data"]["previous"]["reason"] == "duplicate"
    await pse.post(
        f"/api/tickets/{t['id']}/close",
        json={"closure_reason": "duplicate", "note": "Duplicate again"},
    )
    row = await db.get(Ticket, t["id"])
    row.closed_at = now() - timedelta(days=20)
    await db.commit()
    assert (
        await pse.post(f"/api/tickets/{t['id']}/reopen", json={"reason": "Customer called"})
    ).status_code == 403
    crm, _ = await login_as(Role.crm_manager)
    t = (
        await crm.post(
            f"/api/tickets/{t['id']}/reopen", json={"reason": "Escalated by the customer"}
        )
    ).json()
    assert t["reopened_count"] == 2 and t["timeline"][-1]["data"]["authorised_escalation"] is True


async def test_sla_flags_and_lists(login_as, db, case):
    pse, me = await login_as(Role.postsales_exec)
    late = (await raise_(pse, case, priority="urgent")).json()
    row = await db.get(Ticket, late["id"])
    row.response_due_at, row.resolution_due_at = (
        now() - timedelta(hours=1),
        now() - timedelta(minutes=5),
    )
    risky = (await raise_(pse, case, priority="normal", category="kyc")).json()
    row2 = await db.get(Ticket, risky["id"])
    row2.resolution_due_at = now() + timedelta(hours=10)  # under 25% of 7 days left
    await db.commit()
    s = (await pse.get(f"/api/tickets/{late['id']}")).json()["sla"]
    assert s["response_breached"] and s["resolution_breached"] and not s["at_risk"]
    assert [i["id"] for i in (await pse.get("/api/tickets?view=breached")).json()["items"]] == [
        late["id"]
    ]
    assert [i["id"] for i in (await pse.get("/api/tickets?view=at_risk")).json()["items"]] == [
        risky["id"]
    ]
    await pse.post(f"/api/tickets/{risky['id']}/acknowledge", json={"text": "On it"})
    assert [i["id"] for i in (await pse.get("/api/tickets?view=mine")).json()["items"]] == [
        risky["id"]
    ]
    _ = me


async def test_assigning_to_a_team_member(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    _, site = await login_as(Role.site)
    t = (await raise_(pse, case)).json()
    assert (
        await pse.post(f"/api/tickets/{t['id']}/assign", json={"owner_id": site.id})
    ).status_code == 403  # CRM managers assign
    crm, _ = await login_as(Role.crm_manager)
    d = (await crm.get(f"/api/tickets/{t['id']}")).json()
    assert site.id in [u["id"] for u in d["owners"]]
    _, fin_approver = await login_as(Role.auditor)
    assert (
        await crm.post(f"/api/tickets/{t['id']}/assign", json={"owner_id": fin_approver.id})
    ).status_code == 422  # auditors don't handle tickets
    d = (await crm.post(f"/api/tickets/{t['id']}/assign", json={"owner_id": site.id})).json()
    assert d["owner"]["id"] == site.id and d["status"] == "assigned"
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == site.id, Notification.type == "ticket_assigned"
        )
    )
