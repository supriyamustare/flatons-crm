"""Phase 2 gate: report figures reconcile with the records; CPL uses attributed leads;
zero denominators are N/A; CSV export is for admins and managers only."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.demo import DEMO_DOMAIN, seed_demo
from app.models import AuditLog, Campaign, Expense, Role, User
from app.schemas.report import ReportQuery
from app.services import reports as svc
from app.services.receipts import receipts_dir

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 26, 18, 0, tzinfo=IST).astimezone(UTC)
CONN = "('interested','callback','not_interested')"
Q30 = ReportQuery(range="30d")


def period(q):
    today = NOW.astimezone(IST).date()
    s, e = {
        "today": (today, today),
        "7d": (today - timedelta(days=6), today),
        "30d": (today - timedelta(days=29), today),
    }.get(q.range) or (q.date_from, q.date_to)
    return (
        s,
        e,
        datetime.combine(s, time.min, IST),
        datetime.combine(e + timedelta(days=1), time.min, IST),
    )


def r4(n, d):
    return round(n / d, 4) if d else None


@pytest.fixture
async def data(db, make_user):
    admin = await make_user(Role.admin)
    await seed_demo(db, password="demo-pass-123", leads=60, now=NOW)
    await db.commit()
    # Soft-delete the lead with the most calls: it, and its calls and visits, must vanish from every report
    await db.execute(
        text("""UPDATE leads SET deleted_at = now() WHERE id = (
        SELECT lead_id FROM call_logs GROUP BY lead_id ORDER BY count(*) DESC, lead_id LIMIT 1)""")
    )
    await db.commit()
    ravi = await db.scalar(select(User).where(User.email == f"ravi.kumar{DEMO_DOMAIN}"))
    return admin, ravi


async def sql(db, query, **params):
    return (await db.execute(text(query), params)).all()


QUERIES = [
    ReportQuery(range="7d"),
    Q30,
    ReportQuery(range="custom", date_from=date(2026, 9, 15), date_to=date(2026, 10, 10)),
]


@pytest.mark.parametrize("q", QUERIES, ids=lambda q: q.range)
async def test_calls_report_reconciles(db, data, q):
    admin, _ = data
    _, _, ps, pe = period(q)
    rep = await svc.calls_report(db, admin, q, NOW)
    want = {
        r[0]: r[1:]
        for r in await sql(
            db,
            f"""
        SELECT c.user_id, count(*), count(*) FILTER (WHERE c.outcome IN {CONN})
        FROM call_logs c JOIN leads l ON l.id = c.lead_id
        WHERE l.deleted_at IS NULL AND c.called_at >= :ps AND c.called_at < :pe GROUP BY c.user_id""",
            ps=ps,
            pe=pe,
        )
    }
    assert {r.user.id: (r.calls, r.connected) for r in rep.rows} == want
    for r in rep.rows:
        assert r.connection_rate == r4(r.connected, r.calls)
    assert rep.totals.calls == sum(v[0] for v in want.values())
    assert sum(d.calls for d in rep.by_day) == rep.totals.calls
    assert len(rep.by_day) == (rep.date_to - rep.date_from).days + 1


@pytest.mark.parametrize("q", QUERIES, ids=lambda q: q.range)
async def test_visits_report_reconciles(db, data, q):
    admin, _ = data
    _, _, ps, pe = period(q)
    rep = await svc.visits_report(db, admin, q, NOW)
    rows = await sql(
        db,
        """
        SELECT v.host_id, v.project_id, v.visit_source, v.status, count(*)
        FROM site_visits v JOIN leads l ON l.id = v.lead_id
        WHERE l.deleted_at IS NULL AND v.scheduled_at >= :ps AND v.scheduled_at < :pe
        GROUP BY 1, 2, 3, 4""",
        ps=ps,
        pe=pe,
    )

    def tally(key):
        out = {}
        for host, proj, src, status, n in rows:
            k = {"person": host, "project": proj, "source": src}[key]
            d = out.setdefault(
                k, {"visits": 0, "completed": 0, "no_show": 0, "cancelled": 0, "scheduled": 0}
            )
            d["visits"] += n
            d[status] += n
        return out

    got_p = {x.user.id: x for x in rep.by_person}
    for k, d in tally("person").items():
        x = got_p[k]
        assert (x.visits, x.completed, x.no_show, x.cancelled, x.scheduled) == tuple(d.values())
        assert x.completion_rate == r4(d["completed"], d["completed"] + d["no_show"])
    assert {x.project.id: x.visits for x in rep.by_project} == {
        k: d["visits"] for k, d in tally("project").items()
    }
    assert {x.source.value: x.visits for x in rep.by_source} == {
        k: d["visits"] for k, d in tally("source").items()
    }
    assert rep.totals.visits == sum(n for *_, n in rows)


@pytest.mark.parametrize("q", QUERIES, ids=lambda q: q.range)
async def test_conversion_report_reconciles(db, data, q):
    admin, _ = data
    _, _, ps, pe = period(q)
    rep = await svc.conversion_report(db, admin, q, NOW)
    want = {
        r[0]: r[1:]
        for r in await sql(
            db,
            """
        WITH c AS (SELECT l.id, l.assigned_to_id, l.status = 'booked' AS booked,
                          EXISTS (SELECT 1 FROM site_visits v WHERE v.lead_id = l.id AND v.status = 'completed') AS visited
                   FROM leads l WHERE l.deleted_at IS NULL AND l.created_at >= :ps AND l.created_at < :pe)
        SELECT assigned_to_id, count(*), count(*) FILTER (WHERE visited), count(*) FILTER (WHERE booked),
               count(*) FILTER (WHERE visited AND booked) FROM c GROUP BY 1""",
            ps=ps,
            pe=pe,
        )
    }
    got = {
        (x.user.id if x.user else None): (x.leads, x.visited, x.booked, x.booked_after_visit)
        for x in rep.by_person
    }
    assert got == want
    t = rep.totals
    assert t.visit_rate == r4(t.visited, t.leads) and t.conversion_rate == r4(t.booked, t.leads)
    assert t.visit_to_booking_rate == r4(t.booked_after_visit, t.visited)


async def test_campaign_report_reconciles_and_uses_attributed_leads(db, data):
    admin, _ = data
    start, end, ps, pe = period(Q30)
    rep = await svc.campaigns_report(db, admin, Q30, NOW)
    spend = dict(
        await sql(
            db,
            "SELECT campaign_id, sum(amount) FROM expenses WHERE spent_on BETWEEN :s AND :e GROUP BY 1",
            s=start,
            e=end,
        )
    )
    leads = dict(
        await sql(
            db,
            """SELECT campaign_id, count(*) FROM leads WHERE deleted_at IS NULL
        AND created_at >= :ps AND created_at < :pe GROUP BY 1""",
            ps=ps,
            pe=pe,
        )
    )
    for row in rep.rows:
        assert row.spend == spend.get(row.campaign_id, 0)
        assert row.leads == leads.get(row.campaign_id, 0)
        # Gate item 4: cost per lead = this campaign's spend / leads attributed to it
        assert row.cost_per_lead == (round(row.spend / row.leads) if row.leads else None)
    assert rep.unattributed_leads == leads.get(None, 0) > 0
    all_leads = sum(leads.values())
    assert rep.totals.cost_per_lead == round(rep.totals.spend / rep.totals.leads)
    assert rep.totals.cost_per_lead != round(
        rep.totals.spend / all_leads
    )  # not divided by every lead


async def test_zero_denominators_are_na_not_zero(db, data):
    """Gate item 5: the expo has spend but no leads; nothing booked yet means N/A, not 0."""
    admin, _ = data
    rep = await svc.campaigns_report(db, admin, Q30, NOW)
    expo = next(r for r in rep.rows if "expo" in r.name.lower())
    assert expo.spend > 0 and expo.leads == 0
    assert (
        expo.cost_per_lead is None and expo.cost_per_visit is None and expo.cost_per_booking is None
    )
    quiet = await svc.calls_report(
        db,
        admin,
        ReportQuery(range="custom", date_from=date(2025, 1, 1), date_to=date(2025, 1, 5)),
        NOW,
    )
    assert quiet.totals.calls == 0 and quiet.totals.connection_rate is None
    empty = await svc.conversion_report(
        db,
        admin,
        ReportQuery(range="custom", date_from=date(2025, 1, 1), date_to=date(2025, 1, 5)),
        NOW,
    )
    assert (
        empty.totals.visit_rate,
        empty.totals.visit_to_booking_rate,
        empty.totals.conversion_rate,
    ) == (None, None, None)


async def test_staff_report_reconciles(db, data):
    admin, ravi = data
    start, end, ps, pe = period(Q30)
    rep = await svc.staff_report(db, admin, Q30, NOW)
    row = next(r for r in rep.rows if r.user.id == ravi.id)
    ((leads,),) = await sql(
        db,
        "SELECT count(*) FROM leads WHERE deleted_at IS NULL AND assigned_to_id=:u AND created_at>=:ps AND created_at<:pe",
        u=ravi.id,
        ps=ps,
        pe=pe,
    )
    ((calls, conn),) = await sql(
        db,
        f"SELECT count(*), count(*) FILTER (WHERE outcome IN {CONN}) FROM call_logs WHERE user_id=:u AND called_at>=:ps AND called_at<:pe",
        u=ravi.id,
        ps=ps,
        pe=pe,
    )
    ((visits,),) = await sql(
        db,
        "SELECT count(*) FROM site_visits WHERE host_id=:u AND status='completed' AND scheduled_at>=:ps AND scheduled_at<:pe",
        u=ravi.id,
        ps=ps,
        pe=pe,
    )
    ((booked,),) = await sql(
        db,
        "SELECT count(*) FROM leads WHERE deleted_at IS NULL AND assigned_to_id=:u AND status='booked' AND status_changed_at>=:ps AND status_changed_at<:pe",
        u=ravi.id,
        ps=ps,
        pe=pe,
    )
    assert (row.leads, row.calls, row.connected, row.visits_completed, row.bookings) == (
        leads,
        calls,
        conn,
        visits,
        booked,
    )
    assert row.lead_to_booking_rate == r4(booked, leads)


async def test_executive_sees_only_own_figures(db, data):
    _, ravi = data
    team = await svc.calls_report(
        db, (await db.scalar(select(User).where(User.role == Role.admin))), Q30, NOW
    )
    mine = await svc.calls_report(db, ravi, Q30.model_copy(update={"user_id": 999}), NOW)
    assert mine.scope == "mine" and {r.user.id for r in mine.rows} <= {ravi.id}
    assert mine.totals.calls < team.totals.calls


# ---------------------------------------------------------------- permissions & CSV


@pytest.mark.parametrize(
    "role,status", [(Role.admin, 200), (Role.manager, 200), (Role.executive, 403), (Role.docs, 403)]
)
async def test_campaign_report_and_export_permissions(login_as, role, status):
    c, _ = await login_as(role)
    assert (await c.get("/api/reports/campaigns")).status_code == status
    assert (await c.get("/api/reports/staff/export")).status_code == status
    assert (await c.get("/api/expenses")).status_code == status


async def test_executive_can_view_but_not_export(login_as):
    c, _ = await login_as(Role.executive)
    for kind in ("calls", "visits", "conversion", "staff"):
        assert (await c.get(f"/api/reports/{kind}")).status_code == 200
        assert (await c.get(f"/api/reports/{kind}/export")).status_code == 403


async def test_csv_export_content_and_audit(login_as, db):
    mgr, manager = await login_as(Role.manager)
    r = await mgr.get(
        "/api/reports/calls/export",
        params={"range": "custom", "date_from": "2026-01-01", "date_to": "2026-01-31"},
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert (
        'filename="flatons-calls-2026-01-01-to-2026-01-31.csv"' in r.headers["content-disposition"]
    )
    body = r.content.decode("utf-8")
    assert (
        body.startswith("\ufeff") and "Connection rate" in body and "N/A" in body
    )  # no calls -> N/A
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "report.export"))
    assert entry.actor_id == manager.id and entry.entity_id == "calls"


# ---------------------------------------------------------------- campaigns, expenses, receipts

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%fake but well-formed enough header\n"


async def make_campaign(c, name="Google Ads Oct", **kw):
    r = await c.post(
        "/api/campaigns",
        json={"name": name, "channel": "google_ads", "start_date": "2026-10-01", **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_expense_with_receipt_upload_and_download(login_as, db):
    mgr, _ = await login_as(Role.manager)
    camp = await make_campaign(mgr)
    r = await mgr.post(
        "/api/expenses",
        data={
            "campaign_id": camp["id"],
            "spent_on": "2026-10-20",
            "amount": "45000",
            "category": "ad_spend",
            "vendor": "Google",
        },
        files={"receipt": ("invoice.png", PNG, "image/png")},
    )
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["has_receipt"] and e["receipt_name"] == "invoice.png" and e["amount"] == 45000
    stored = await db.scalar(select(Expense.receipt_path))
    assert (
        receipts_dir() / stored
    ).read_bytes() == PNG and "invoice" not in stored  # random name on disk
    dl = await mgr.get(f"/api/expenses/{e['id']}/receipt")
    assert dl.status_code == 200 and dl.content == PNG and dl.headers["content-type"] == "image/png"
    ex, _ = await login_as(Role.executive)
    assert (await ex.get(f"/api/expenses/{e['id']}/receipt")).status_code == 403
    assert (await mgr.delete(f"/api/expenses/{e['id']}")).status_code == 204
    assert not (receipts_dir() / stored).exists()


@pytest.mark.parametrize(
    "name,content",
    [
        ("invoice.pdf", b"MZ\x90\x00 this is really a program"),
        ("photo.jpg", b"<html>not an image</html>"),
        ("big.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024 + 10)),
        ("empty.pdf", b""),
    ],
    ids=["disguised-program", "html-as-jpg", "over-10mb", "empty"],
)
async def test_bad_receipts_rejected(login_as, db, name, content):
    mgr, _ = await login_as(Role.manager)
    camp = await make_campaign(mgr)
    r = await mgr.post(
        "/api/expenses",
        data={
            "campaign_id": camp["id"],
            "spent_on": "2026-10-20",
            "amount": "100",
            "category": "other",
        },
        files={"receipt": (name, content, "application/pdf")},
    )
    assert r.status_code == 422
    assert await db.scalar(select(Expense.id)) is None
    assert list(receipts_dir().iterdir()) == [] or all(
        p.stat().st_size for p in receipts_dir().iterdir()
    )


async def test_pdf_receipt_and_replace(login_as, db):
    mgr, _ = await login_as(Role.manager)
    camp = await make_campaign(mgr)
    e = (
        await mgr.post(
            "/api/expenses",
            data={
                "campaign_id": camp["id"],
                "spent_on": "2026-10-20",
                "amount": "100",
                "category": "other",
            },
        )
    ).json()
    assert e["has_receipt"] is False
    r = await mgr.post(
        f"/api/expenses/{e['id']}/receipt", files={"receipt": ("bill.pdf", PDF, "application/pdf")}
    )
    assert r.status_code == 200 and r.json()["has_receipt"]


@pytest.mark.parametrize("amount", ["0", "-5", "abc"])
async def test_expense_amount_must_be_positive(login_as, amount):
    mgr, _ = await login_as(Role.manager)
    camp = await make_campaign(mgr)
    r = await mgr.post(
        "/api/expenses",
        data={
            "campaign_id": camp["id"],
            "spent_on": "2026-10-20",
            "amount": amount,
            "category": "other",
        },
    )
    assert r.status_code == 422


async def test_campaign_rules(login_as, db):
    mgr, _ = await login_as(Role.manager)
    assert (
        await mgr.post(
            "/api/campaigns",
            json={
                "name": "X",
                "channel": "event",
                "start_date": "2026-10-10",
                "end_date": "2026-10-01",
            },
        )
    ).status_code == 422
    camp = await make_campaign(mgr)
    assert (
        await mgr.post(
            "/api/campaigns",
            json={"name": "google ads oct", "channel": "event", "start_date": "2026-10-01"},
        )
    ).status_code == 409
    lead = (
        await mgr.post(
            "/api/leads",
            json={
                "name": "A",
                "mobile": "9876543210",
                "source": "google_ads",
                "campaign_id": camp["id"],
            },
        )
    ).json()["lead"]
    assert lead["campaign"]["name"] == "Google Ads Oct"
    assert (
        await mgr.post(
            "/api/leads",
            json={"name": "B", "mobile": "9123456780", "source": "99acres", "campaign_id": 999},
        )
    ).status_code == 422
    assert (
        await mgr.delete(f"/api/campaigns/{camp['id']}")
    ).status_code == 409  # a lead is attributed
    other = await make_campaign(mgr, name="Unused")
    assert (await mgr.delete(f"/api/campaigns/{other['id']}")).status_code == 204
    ex, _ = await login_as(Role.executive)
    assert (await ex.get("/api/campaigns")).status_code == 200  # to pick one on a lead
    assert (
        await ex.post(
            "/api/campaigns", json={"name": "Y", "channel": "event", "start_date": "2026-10-01"}
        )
    ).status_code == 403


async def test_expense_list_totals(login_as, data, db):
    c, _ = await login_as(Role.admin)
    page = (await c.get("/api/expenses", params={"page_size": 100})).json()
    ((n, total),) = await sql(db, "SELECT count(*), sum(amount) FROM expenses")
    assert page["total"] == n and page["total_amount"] == total
    assert sum(page["by_channel"].values()) == total
    camp = await db.scalar(select(Campaign.id).where(Campaign.name.like("%expo%")))
    just_expo = (await c.get("/api/expenses", params={"campaign_id": camp})).json()
    assert just_expo["total"] == 1 and just_expo["total_amount"] == 85_000
