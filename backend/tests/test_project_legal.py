import json

import pytest
from sqlalchemy import select, text

from app.models import AuditLog, Role
from app.services import doc_readiness
from tests.conftest import new_project

LEGAL = {
    "developer_legal_name": "Avnee Estates LLP",
    "rera_number": "p52100012345",
    "registered_address": "Kharadi, Pune 411014",
    "signatory_name": "Rahul Avnee",
    "signatory_designation": "Partner",
    "gstin": "27aabfa1234c1z5",
}
BANK = {
    "bank_name": "HDFC Bank",
    "account_holder_name": "Avnee Estates LLP - Habitat Collection A/c",
    "account_number": "5020 0012 3456 78",
    "ifsc": "hdfc0001234",
    "branch": "Kharadi, Pune",
}
STAGES = {"stages": [{"name": "Booking", "pct": 10}, {"name": "Rest", "pct": 90}]}


@pytest.fixture
async def project(db):
    p = await new_project(db, "Habitat")
    await db.commit()
    return p


async def test_legal_details_saved_cleaned_and_validated(login_as, project, db):
    admin, _ = await login_as(Role.admin)
    r = await admin.put(f"/api/projects/{project.id}/legal", json=LEGAL)
    assert r.status_code == 200, r.text
    assert (r.json()["rera_number"], r.json()["gstin"], r.json()["cin"]) == (
        "P52100012345",
        "27AABFA1234C1Z5",
        None,
    )
    for bad in (
        {"gstin": "27AABFA1234C1Z"},
        {"cin": "X12345"},
        {"rera_number": "<b>"},
        {"developer_legal_name": "<script>"},
    ):
        assert (
            await admin.put(f"/api/projects/{project.id}/legal", json={**LEGAL, **bad})
        ).status_code == 422, bad
    ok_cin = await admin.put(
        f"/api/projects/{project.id}/legal", json={**LEGAL, "cin": "u70100mh2015ptc123456"}
    )
    assert ok_cin.json()["cin"] == "U70100MH2015PTC123456"
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "project.legal"))


async def test_who_can_see_and_change_legal_details(login_as, project):
    admin, _ = await login_as(Role.admin)
    await admin.put(f"/api/projects/{project.id}/legal", json=LEGAL)
    mgr, _ = await login_as(Role.manager)
    assert (await mgr.get(f"/api/projects/{project.id}/legal")).json()[
        "developer_legal_name"
    ] == "Avnee Estates LLP"
    assert (await mgr.put(f"/api/projects/{project.id}/legal", json=LEGAL)).status_code == 403
    ex, _ = await login_as(Role.executive)
    assert (await ex.get(f"/api/projects/{project.id}/legal")).status_code == 403


async def test_bank_account_number_is_encrypted_masked_and_reveal_is_logged(login_as, project, db):
    admin, _ = await login_as(Role.admin)
    r = await admin.put(f"/api/projects/{project.id}/bank", json=BANK)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["account_number_masked"], b["account_number"], b["ifsc"]) == (
        "••••5678",
        None,
        "HDFC0001234",
    )
    stored = await db.scalar(text("SELECT account_number_enc FROM project_bank_details"))
    assert "50200012345678" not in stored and "5678" not in stored  # encrypted at rest
    assert (await admin.get(f"/api/projects/{project.id}/bank")).json()["account_number"] is None
    revealed = await admin.get(f"/api/projects/{project.id}/bank", params={"reveal": True})
    assert revealed.json()["account_number"] == "50200012345678"
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "project.bank_revealed"))
    logged = [
        json.dumps(a.details)
        for a in await db.scalars(select(AuditLog).where(AuditLog.action == "project.bank"))
    ]
    assert logged and not any(
        "50200012345678" in x for x in logged
    )  # the number itself is never logged
    # Updating without the number keeps the saved one
    r = await admin.put(
        f"/api/projects/{project.id}/bank",
        json={**BANK, "account_number": None, "branch": "Viman Nagar"},
    )
    assert (r.json()["branch"], r.json()["account_number_masked"]) == ("Viman Nagar", "••••5678")


@pytest.mark.parametrize(
    "bad", [{"ifsc": "HDFC123"}, {"account_number": "12AB34"}, {"account_number": "12345"}]
)
async def test_bank_details_validated(login_as, project, bad):
    admin, _ = await login_as(Role.admin)
    assert (
        await admin.put(f"/api/projects/{project.id}/bank", json={**BANK, **bad})
    ).status_code == 422


async def test_bank_details_are_admin_only(login_as, project):
    for role in (Role.manager, Role.executive, Role.docs):
        c, _ = await login_as(role)
        assert (await c.get(f"/api/projects/{project.id}/bank")).status_code == 403
        assert (await c.put(f"/api/projects/{project.id}/bank", json=BANK)).status_code == 403


async def test_readiness_lists_what_is_missing_until_complete(login_as, project, db):
    admin, _ = await login_as(Role.admin)
    docs, _ = await login_as(Role.docs)
    r = (await docs.get(f"/api/projects/{project.id}/doc-readiness")).json()
    assert (
        not r["ready"]
        and len(r["missing"]) == 12
        and "GSTIN" in r["missing"]
        and "Payment schedule" in r["missing"]
    )
    with pytest.raises(doc_readiness.NotReady, match="Complete the project's details first"):
        await doc_readiness.require_ready(db, project)

    await admin.put(f"/api/projects/{project.id}/legal", json=LEGAL)
    await admin.put(f"/api/projects/{project.id}/bank", json={**BANK, "branch": None})
    r = (await docs.get(f"/api/projects/{project.id}/doc-readiness")).json()
    assert (
        r["missing"] == ["Branch", "Payment schedule"] and r["legal_missing"] == []
    )  # CIN is optional
    tpl = (await admin.get(f"/api/projects/{project.id}/cost-sheet")).json()
    await admin.put(f"/api/projects/{project.id}/cost-sheet", json={**tpl, **STAGES})
    await admin.put(f"/api/projects/{project.id}/bank", json={"branch": "Kharadi"})
    r = (await docs.get(f"/api/projects/{project.id}/doc-readiness")).json()
    assert r["ready"] and r["missing"] == [] and r["schedule_note"] == "2 payment stages, 100%"
    await db.refresh(project)
    await doc_readiness.require_ready(db, project)  # no longer raises
    ex, _ = await login_as(Role.executive)
    assert (await ex.get(f"/api/projects/{project.id}/doc-readiness")).status_code == 403


async def test_cost_sheet_uses_the_official_name_and_rera(login_as, project, db):
    admin, _ = await login_as(Role.admin)
    b = (await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "Habitat"})).json()
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": 1, "floor_to": 1, "units_per_floor": 1, "unit_type": "studio"},
    )
    unit_id = await db.scalar(text("SELECT id FROM units LIMIT 1"))
    before = (await admin.get(f"/api/units/{unit_id}/cost-sheet")).json()
    await admin.put(f"/api/projects/{project.id}/legal", json=LEGAL)
    after = (await admin.get(f"/api/units/{unit_id}/cost-sheet")).json()
    assert before["rera_number"] != "P52100012345"
    assert (after["developer_name"], after["rera_number"]) == ("Avnee Estates LLP", "P52100012345")
