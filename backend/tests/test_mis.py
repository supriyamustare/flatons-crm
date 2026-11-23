from datetime import timedelta

from sqlalchemy import select

from app.models import PostSalesCase, Role
from app.models.followup import FollowUpChannel, FollowUpOutcome, PaymentFollowUp
from app.models.ledger import Ledger
from app.services.mis import take_snapshot
from tests import test_ledger
from tests.test_demands import approved_ledger, project_id
from tests.test_ledger import PAID, TODAY

case = test_ledger.case


async def setup_money(login_as, db, case_id):
    """Booking paid and confirmed; Plinth demanded 40 days ago and unpaid; 1st Slab due in 5 days."""
    fin, chk = await approved_ledger(login_as, case_id)
    rid = (await chk.get(f"/api/post-sales/cases/{case_id}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case_id}/receipts/{rid}/confirm")
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case_id))
    await db.refresh(ledger)
    by = {i.name: i for i in ledger.schedule}
    by["Plinth"].demanded_on, by["Plinth"].due_date = (
        TODAY - timedelta(days=55),
        TODAY - timedelta(days=40),
    )
    by["1st Slab"].demanded_on, by["1st Slab"].due_date = (
        TODAY - timedelta(days=10),
        TODAY + timedelta(days=5),
    )
    await db.commit()
    return by["Plinth"].amount + by["Plinth"].gst, by["1st Slab"].amount + by["1st Slab"].gst


async def test_dashboard_and_finance_figures(login_as, db, case):
    plinth, slab = await setup_money(login_as, db, case)
    mgmt, _ = await login_as(Role.management)
    d = (await mgmt.get("/api/mis/dashboard")).json()
    assert (
        d["headline"]["active_accounts"] == 1
        and d["headline"]["agreements_pending"] == 1
        and d["headline"]["overdue_receivables"] == plinth
    )
    assert next(e for e in d["exceptions"] if e["key"] == "overdue")["count"] == 1
    f = (await mgmt.get("/api/mis/reports/finance")).json()
    p = f["projects"][0]
    assert p["collected"] == PAID and p["consideration"] > 0 and f["totals"]["collected"] == PAID
    assert f["ageing"]["31-60"] == plinth and f["ageing"]["1-30"] == 0
    assert (
        f["upcoming"]["7"]["count"] == 1
        and f["upcoming"]["7"]["amount"] == slab
        and f["upcoming"]["7"]["items"][0]["stage"] == "1st Slab"
    )
    booking_due = p["due_total"] - plinth  # Booking (paid) + Plinth (unpaid) are due
    assert p["collection_efficiency_pct"] == round(100 * PAID / (booking_due + plinth), 1)
    assert set(f["not_available"]) == {"unmatched_bank_transactions", "waivers", "tax_tds"}
    c = f["customers"][0]
    assert c["overdue"] == plinth and c["demanded_not_due"] == slab


async def test_period_figures(login_as, db, case):
    await setup_money(login_as, db, case)
    fin, _ = await login_as(Role.finance)
    f = (
        await fin.get(
            f"/api/mis/reports/finance?period_from={(TODAY + timedelta(days=1)).isoformat()}&period_to={(TODAY + timedelta(days=30)).isoformat()}"
        )
    ).json()
    assert f["totals"]["collected"] == 0  # nothing received in that period
    assert (
        await fin.get("/api/mis/reports/finance?period_from=2026-12-01&period_to=2026-11-01")
    ).status_code == 422


async def test_operations_reports(login_as, db, case):
    await setup_money(login_as, db, case)
    c = await db.get(PostSalesCase, case)
    db.add(
        PaymentFollowUp(
            case_id=case,
            channel=FollowUpChannel.call,
            outcome=FollowUpOutcome.promised,
            contacted_on=TODAY - timedelta(days=12),
            promise_date=TODAY - timedelta(days=2),
            promise_amount=100_000,
            next_follow_up_on=TODAY - timedelta(days=1),
        )
    )
    await db.commit()
    pse, _ = await login_as(Role.postsales_exec)
    await pse.post(
        f"/api/post-sales/cases/{case}/tickets",
        data={
            "category": "payment",
            "title": "Plinth demand query",
            "description": "Customer asks about GST",
            "priority": "high",
        },
    )
    crm, _ = await login_as(Role.crm_manager)
    o = (await crm.get("/api/mis/reports/operations")).json()
    assert o["broken_promises"][0]["promise_amount"] == 100_000
    assert o["overdue_follow_ups"][0]["days"] == 1
    assert o["kyc_incomplete"] and o["kyc_incomplete"][0]["case_id"] == case
    assert o["agreements_by_stage"] == {"not_started": 1}
    assert (
        o["tickets_by_team"]["Finance"]["high"] == 1
        and o["tickets_by_team"]["Finance"]["0-2 days"] == 1
    )
    if c.owner_id:
        assert any(w["cases"] == 1 for w in o["workload"])


async def test_filters_roles_export_and_snapshots(login_as, db, case):
    await setup_money(login_as, db, case)
    pse, _ = await login_as(Role.postsales_exec)
    assert (await pse.get("/api/mis/dashboard")).status_code == 403
    aud, _ = await login_as(Role.auditor)
    pid = await project_id(db, case)
    assert (await aud.get(f"/api/mis/dashboard?project_id={pid}")).json()["headline"][
        "active_accounts"
    ] == 1
    assert (await aud.get(f"/api/mis/dashboard?project_id={pid + 999}")).json()["headline"][
        "active_accounts"
    ] == 0
    assert (
        await aud.get(f"/api/mis/dashboard?booking_from={(TODAY + timedelta(days=1)).isoformat()}")
    ).json()["headline"]["active_accounts"] == 0
    r = await aud.get("/api/mis/export/finance/customers")
    assert (
        r.status_code == 200
        and r.headers["content-type"].startswith("text/csv")
        and "case_code" in r.text.splitlines()[0]
        and len(r.text.splitlines()) == 2
    )
    assert (await aud.get("/api/mis/export/finance/upcoming_7")).text.count("\n") == 2
    assert (await aud.get("/api/mis/export/finance/nonsense")).status_code == 404
    assert await take_snapshot(db) >= 2  # all projects + each project
    await db.commit()
    snaps = (await aud.get("/api/mis/snapshots")).json()
    assert snaps[0]["taken_on"] == TODAY.isoformat() and snaps[0]["active_accounts"] == 1
    assert await take_snapshot(db) >= 2  # re-running the same day updates, not duplicates
    await db.commit()
    assert len((await aud.get("/api/mis/snapshots")).json()) == 1
