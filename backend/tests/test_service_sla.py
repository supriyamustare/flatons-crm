from datetime import timedelta

from sqlalchemy import select

from app.models import Notification, Role
from app.models.ticket import Ticket
from app.services.notifications import notify
from app.services.tickets import now, run_escalations
from tests import test_ledger
from tests.test_tickets import raise_

case = test_ledger.case


async def settings(c):
    return (await c.get("/api/service/settings")).json()


def body(s, **over):
    keep = {
        k: s[k]
        for k in (
            "response_hours",
            "resolution_hours",
            "at_risk_pct",
            "reopen_days",
            "categories",
            "escalation",
        )
    }
    return {**keep, **over}


async def test_settings_are_admin_only_validated_and_apply_to_new_tickets(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    old = (
        await raise_(pse, case, category="kyc", priority="normal")
    ).json()  # raised under the defaults
    crm, _ = await login_as(Role.crm_manager)
    s = await settings(crm)
    assert (
        s["can_edit"] is False
        and s["resolution_hours"]["normal"] == 168
        and s["categories"]["defect"]["needs_confirmation"] is True
    )
    assert (await crm.put("/api/service/settings", json=body(s))).status_code == 403
    admin, _ = await login_as(Role.admin)
    bad = body(s, response_hours={**s["response_hours"], "normal": 500})
    r = await admin.put("/api/service/settings", json=bad)
    assert r.status_code == 422 and "response target can't be longer" in r.text
    cats = {**s["categories"], "kyc": {"team": "legal", "needs_confirmation": True}}
    r = await admin.put(
        "/api/service/settings",
        json=body(s, resolution_hours={**s["resolution_hours"], "normal": 48}, categories=cats),
    )
    assert r.status_code == 200 and r.json()["resolution_hours"]["normal"] == 48
    new = (await raise_(pse, case, category="kyc", priority="normal")).json()
    row_new, row_old = await db.get(Ticket, new["id"]), await db.get(Ticket, old["id"])
    assert (row_new.resolution_window_h, row_new.needs_confirmation, new["team"]) == (
        48,
        True,
        "legal",
    )
    assert (row_old.resolution_window_h, row_old.needs_confirmation, old["team"]) == (
        168,
        False,
        "crm",
    )  # unchanged


async def test_escalation_levels_fire_once_each_with_rule_recipients_and_date(login_as, db, case):
    pse, owner = await login_as(Role.postsales_exec)
    _, crm = await login_as(Role.crm_manager)
    _, mgmt = await login_as(Role.management)
    t = (await raise_(pse, case, priority="high")).json()
    await pse.post(f"/api/tickets/{t['id']}/acknowledge", json={"text": "On it"})  # owner = pse
    row = await db.get(Ticket, t["id"])
    row.resolution_due_at = now() + timedelta(hours=2)  # at risk (under 25% of 72 h)
    await db.commit()
    assert (await run_escalations(db, now(), notify)) == {"level1": 1, "level2": 0, "level3": 0}
    await db.commit()
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == owner.id, Notification.type == "ticket_escalated"
        )
    )
    assert (await run_escalations(db, now(), notify))["level1"] == 0  # once
    row.resolution_due_at = now() - timedelta(hours=30)  # breached by more than 24 h
    await db.commit()
    assert (await run_escalations(db, now(), notify)) == {"level1": 0, "level2": 1, "level3": 1}
    await db.commit()
    for uid in (crm.id, mgmt.id):
        assert await db.scalar(
            select(Notification.id).where(
                Notification.user_id == uid, Notification.type == "ticket_escalated"
            )
        )
    d = (await pse.get(f"/api/tickets/{t['id']}")).json()
    assert [e["level"] for e in d["escalations"]] == [1, 2, 3] and d["escalations"][1][
        "rule"
    ] == "Resolution target breached"
    assert (
        "Management" not in d["escalations"][0]["recipients"]
        and d["escalations"][2]["recipients"]
        and d["escalations"][0]["at"]
    )


async def test_paused_tickets_dont_escalate_and_reopening_starts_again(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    t = (await raise_(pse, case, category="payment", priority="high")).json()
    await pse.post(f"/api/tickets/{t['id']}/acknowledge", json={"text": "Checking"})
    await pse.post(
        f"/api/tickets/{t['id']}/status",
        json={"status": "waiting_customer", "note": "Asked for the UTR"},
    )
    row = await db.get(Ticket, t["id"])
    row.resolution_due_at = now() - timedelta(hours=5)
    await db.commit()
    assert sum((await run_escalations(db, now(), notify)).values()) == 0  # paused
    await pse.post(
        f"/api/tickets/{t['id']}/close",
        json={"closure_reason": "no_response", "note": "No reply after 3 calls"},
    )
    row.escalation_level = 2
    await db.commit()
    d = (
        await pse.post(f"/api/tickets/{t['id']}/reopen", json={"reason": "Customer called back"})
    ).json()
    await db.refresh(row)
    assert row.escalation_level == 0 and d["status"] == "in_progress"


async def test_reports_exclude_paused_time_and_count_breaches_reopens_and_satisfaction(
    login_as, db, case
):
    pse, _ = await login_as(Role.postsales_exec)
    a = (
        await raise_(pse, case, category="document", priority="low", title="Statement please")
    ).json()
    b = (await raise_(pse, case, category="payment", priority="normal")).json()
    await pse.post(f"/api/tickets/{a['id']}/acknowledge", json={"text": "Sure"})
    await pse.post(f"/api/tickets/{a['id']}/propose", json={"text": "Emailed"})
    await pse.post(f"/api/tickets/{a['id']}/close", json={"closure_reason": "resolved"})
    ra, rb = await db.get(Ticket, a["id"]), await db.get(Ticket, b["id"])
    start = now() - timedelta(hours=10)
    ra.created_at, ra.acknowledged_at, ra.resolved_at = (
        start,
        start + timedelta(hours=2),
        start + timedelta(hours=8),
    )
    ra.paused_seconds_customer, ra.csat, ra.reopened_count = 3 * 3600, 5, 1
    rb.response_due_at, rb.resolution_due_at = (
        now() - timedelta(hours=1),
        now() - timedelta(minutes=10),
    )  # breached, never answered
    await db.commit()
    crm, _ = await login_as(Role.crm_manager)
    r = (await crm.get("/api/service/reports")).json()
    o = r["overall"]
    assert (o["raised"], o["closed"], o["open"]) == (2, 1, 1)
    assert o["first_response_avg_h"] == 2.0 and o["resolution_avg_h"] == 5.0  # 8 h minus 3 h paused
    assert (
        o["paused_customer_h"] == 3.0
        and o["response_breaches"] == 1
        and o["resolution_breaches"] == 1
    )
    assert o["reopened"] == 1 and o["csat_avg"] == 5.0 and o["csat_distribution"]["5"] == 1
    assert (
        set(r["by_category"]) == {"document", "payment"} and r["by_team"]["finance"]["raised"] == 1
    )
    assert (
        await crm.get("/api/service/reports?start=2026-12-01&end=2026-11-01")
    ).status_code == 422
