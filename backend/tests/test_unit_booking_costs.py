from sqlalchemy import select

from app.models import PostSalesCase, Role
from app.models.audit import AuditLog
from tests import test_ledger

case = test_ledger.case
PDF = b"%PDF-1.4\nsigned cost sheet"


async def unit_id(db, case_id) -> int:
    c = await db.get(PostSalesCase, case_id)
    return c.booking.unit_id


async def test_parking_is_part_of_the_agreement_value(login_as, db, case):
    uid = await unit_id(db, case)
    mgr, _ = await login_as(Role.manager)
    before = (await mgr.get(f"/api/units/{uid}/cost-sheet")).json()
    keep = dict(before["overrides"] or {})
    r = await mgr.put(
        f"/api/units/{uid}/cost-sheet",
        json={**keep, "parking_no": "P-12", "parking_charges": 300_000},
    )
    assert r.status_code == 200, r.text
    after = r.json()
    assert (after["parking_no"], after["parking_charges"]) == ("P-12", 300_000)
    assert (
        after["base_cost"] == before["cost"]
        and after["cost"] == before["cost"] + 300_000
        and after["rate_psf"] == before["rate_psf"]
    )
    assert (
        after["gst"] > before["gst"]
        and after["stamp_duty"] > before["stamp_duty"]
        and after["grand_total"] > before["grand_total"] + 300_000
    )
    assert (
        sum(st["amount"] for st in after["stages"]) == after["cost"]
    )  # the payment stages cover the parking too
    for k, v in keep.items():
        assert after["overrides"][k] == v  # the flat's other numbers are kept


async def test_the_ledger_shows_parking_separately(login_as, db, case):
    uid = await unit_id(db, case)
    mgr, _ = await login_as(Role.manager)
    keep = dict((await mgr.get(f"/api/units/{uid}/cost-sheet")).json()["overrides"] or {})
    await mgr.put(
        f"/api/units/{uid}/cost-sheet",
        json={**keep, "parking_no": "P-12", "parking_charges": 300_000},
    )
    sheet = (await mgr.get(f"/api/units/{uid}/cost-sheet")).json()
    fin, _ = await login_as(Role.finance)
    led = (await fin.post(f"/api/post-sales/cases/{case}/ledger/generate")).json()
    heads = {c["head"]: c["amount"] for c in led["charges"]}
    assert heads["parking"] == 300_000 and heads["base_price"] == sheet["base_cost"]
    r = await fin.post(f"/api/post-sales/cases/{case}/ledger/submit")
    assert r.status_code == 200, (
        r.text
    )  # the schedule still equals the agreement value, GST still matches


async def test_files_on_a_flat(login_as, db, case):
    uid = await unit_id(db, case)
    mgr, _ = await login_as(Role.manager)
    ex, _ = await login_as(Role.executive)
    assert (
        await ex.post(f"/api/units/{uid}/files", files={"file": ("x.pdf", PDF, "application/pdf")})
    ).status_code == 403
    files = (
        await mgr.post(
            f"/api/units/{uid}/files",
            data={"title": "Signed cost sheet"},
            files={"file": ("cs.pdf", PDF, "application/pdf")},
        )
    ).json()
    assert files[0]["title"] == "Signed cost sheet" and files[0]["uploaded_by"]
    assert [f["title"] for f in (await ex.get(f"/api/units/{uid}/files")).json()] == [
        "Signed cost sheet"
    ]
    dl = await ex.get(files[0]["url"])
    assert dl.status_code == 200 and dl.content.startswith(b"%PDF")
    bad = await mgr.post(
        f"/api/units/{uid}/files",
        files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert bad.status_code == 422
    assert (await ex.delete(f"/api/units/files/{files[0]['id']}")).status_code == 403
    assert (await mgr.delete(f"/api/units/files/{files[0]['id']}")).json() == []
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "unit.file_removed"))
