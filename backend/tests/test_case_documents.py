from sqlalchemy import select

from app.models import AuditLog, Role
from tests import test_ledger
from tests.test_ledger import TODAY

case = test_ledger.case  # booked unit, handover accepted
PNG = b"\x89PNG\r\n\x1a\n"
PDF = b"%PDF-1.4\n"


def f(n: int, kind=PDF):
    return kind + bytes([n % 256]) * 40 + str(n).encode()


async def up(c, case_id, n=1, **form):
    data = {
        "category": "agreements",
        "doc_type": "Sale agreement draft",
        "title": "Draft agreement",
        **{k: str(v) for k, v in form.items()},
    }
    return await c.post(
        f"/api/post-sales/cases/{case_id}/documents",
        data=data,
        files={"file": (f"doc{n}.pdf", f(n), "application/pdf")},
    )


async def folder(c, case_id):
    return (await c.get(f"/api/post-sales/cases/{case_id}/documents")).json()


async def test_the_eleven_categories_and_who_sees_them(login_as, case):
    expectations = {Role.postsales_exec: 11, Role.legal: 8, Role.site: 7, Role.finance: 10}
    for role, n in expectations.items():
        c, _ = await login_as(role)
        cats = (await folder(c, case))["categories"]
        assert len(cats) == n, (role, [x["key"] for x in cats])
    pse, _ = await login_as(Role.postsales_exec)
    labels = [x["label"] for x in (await folder(pse, case))["categories"]]
    assert labels[0] == "01 Booking & Application" and labels[-1] == "11 Other Project Documents"
    ex, _ = await login_as(Role.executive)
    assert (await ex.get(f"/api/post-sales/cases/{case}/documents")).status_code == 403


async def test_upload_checks(login_as, case):
    legal, _ = await login_as(Role.legal)
    r = await up(
        legal, case, doc_number="agr-001", doc_date=TODAY.isoformat(), linked_ref="BKG-00001"
    )
    assert r.status_code == 201, r.text
    d = r.json()["documents"][0]
    assert (
        d["doc_no"].startswith("DOC-"),
        d["verification"],
        d["approval"],
        d["visibility"],
        d["version"],
        len(d["sha256"]),
    ) == (True, "pending", "under_approval", "internal", 1, 64)
    assert (await up(legal, case, n=1)).status_code == 409  # the same file again
    r = await up(legal, case, n=2, doc_number="AGR-001")
    assert (
        r.status_code == 409 and "already in 03 Agreements & Legal" in r.text
    )  # same number, any case
    r = await legal.post(
        f"/api/post-sales/cases/{case}/documents",
        data={"category": "agreements", "doc_type": "x x", "title": "Program"},
        files={"file": ("a.pdf", b"MZ\x90\x00 not a document", "application/pdf")},
    )
    assert r.status_code == 422
    from datetime import timedelta

    assert (
        await up(legal, case, n=3, doc_date=(TODAY + timedelta(days=1)).isoformat())
    ).status_code == 422
    assert (
        await up(
            legal,
            case,
            n=4,
            doc_date=TODAY.isoformat(),
            expiry_date=(TODAY - timedelta(days=1)).isoformat(),
        )
    ).status_code == 422
    site, _ = await login_as(Role.site)
    r = await up(site, case, n=5)
    assert r.status_code == 403 and "can't upload to 03 Agreements & Legal" in r.text
    assert (
        await up(
            site,
            case,
            n=6,
            category="construction",
            doc_type="Progress report",
            title="November progress",
        )
    ).status_code == 201


async def test_review_by_someone_else_with_the_right_role(login_as, db, case):
    legal, _ = await login_as(Role.legal)
    d = (await up(legal, case)).json()["documents"][0]
    assert d["can_review"] is False
    assert (
        await legal.post(f"/api/post-sales/documents/{d['id']}/approve")
    ).status_code == 403  # own upload
    other_legal, _ = await login_as(Role.legal)
    r = await other_legal.post(f"/api/post-sales/documents/{d['id']}/approve")
    assert (
        r.status_code == 200
        and r.json()["documents"][0]["verification"] == "verified"
        and r.json()["documents"][0]["approval"] == "approved"
    )
    # Loan papers are reviewed by a finance approver, not a CRM manager
    pse, _ = await login_as(Role.postsales_exec)
    loan = (
        await up(pse, case, n=2, category="loan", doc_type="Sanction letter", title="HDFC sanction")
    ).json()["documents"][0]
    crm, _ = await login_as(Role.crm_manager)
    assert (await crm.post(f"/api/post-sales/documents/{loan['id']}/approve")).status_code == 403
    chk, _ = await login_as(Role.finance_approver)
    r = await chk.post(
        f"/api/post-sales/documents/{loan['id']}/reject", json={"reason": "Page 2 missing"}
    )
    rej = next(x for x in r.json()["documents"] if x["id"] == loan["id"])
    assert (rej["verification"], rej["approval"], rej["status_reason"]) == (
        "rejected",
        "rejected",
        "Page 2 missing",
    )  # kept in the history
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "document.rejected"))


async def test_release_withdraw_and_new_versions(login_as, case):
    legal, _ = await login_as(Role.legal)
    crm, _ = await login_as(Role.crm_manager)
    d = (await up(legal, case, doc_number="AGR-001")).json()["documents"][0]
    await crm.post(f"/api/post-sales/documents/{d['id']}/approve")
    pse, _ = await login_as(Role.postsales_exec)
    assert (await pse.post(f"/api/post-sales/documents/{d['id']}/release")).status_code == 403
    r = await crm.post(f"/api/post-sales/documents/{d['id']}/release")
    rel = r.json()["documents"][0]
    assert (rel["approval"], rel["visibility"]) == ("released", "customer")
    # A new version needs a reason; the released old version stops being visible to the customer
    r = await legal.post(
        f"/api/post-sales/cases/{case}/documents",
        data={
            "category": "agreements",
            "doc_type": "Sale agreement draft",
            "title": "Draft agreement",
            "doc_number": "AGR-001",
            "replaces_id": str(d["id"]),
        },
        files={"file": ("v2.pdf", f(9), "application/pdf")},
    )
    assert r.status_code == 422 and "reason for the new version" in r.text
    r = await legal.post(
        f"/api/post-sales/cases/{case}/documents",
        data={
            "category": "agreements",
            "doc_type": "Sale agreement draft",
            "title": "Draft agreement",
            "doc_number": "AGR-001",
            "replaces_id": str(d["id"]),
            "version_reason": "Clause 7 corrected",
        },
        files={"file": ("v2.pdf", f(9), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    docs = {x["id"]: x for x in r.json()["documents"]}
    new = next(x for x in docs.values() if x["version"] == 2)
    old = docs[d["id"]]
    assert (new["supersedes"], new["version_reason"], new["approval"]) == (
        d["doc_no"],
        "Clause 7 corrected",
        "under_approval",
    )
    assert (
        old["superseded"]
        and old["approval"] == "withdrawn"
        and old["visibility"] == "internal"
        and "Clause 7 corrected" in old["status_reason"]
    )
    assert (
        await crm.post(f"/api/post-sales/documents/{old['id']}/approve")
    ).status_code == 422  # replaced: no more actions
    # Withdrawing needs a reason
    await crm.post(f"/api/post-sales/documents/{new['id']}/approve")
    assert (
        await crm.post(f"/api/post-sales/documents/{new['id']}/withdraw", json={"reason": "no"})
    ).status_code == 422
    w = (
        await crm.post(
            f"/api/post-sales/documents/{new['id']}/withdraw",
            json={"reason": "Sent to the wrong customer"},
        )
    ).json()
    assert next(x for x in w["documents"] if x["id"] == new["id"])["approval"] == "withdrawn"


async def test_downloads_are_logged_and_restricted(login_as, db, case):
    crm, _ = await login_as(Role.crm_manager)
    pse, _ = await login_as(Role.postsales_exec)
    d = (
        await up(crm, case, n=3, category="payments", doc_type="Tax certificate", title="Form 16B")
    ).json()["documents"][0]
    r = await pse.get(d["url"])
    assert (
        r.status_code == 200
        and r.content.startswith(PDF)
        and r.headers["cache-control"] == "private, no-store"
    )
    assert await db.scalar(
        select(AuditLog.id).where(
            AuditLog.action == "document.downloaded", AuditLog.entity_id == str(d["id"])
        )
    )
    site, _ = await login_as(Role.site)
    assert (await site.get(d["url"])).status_code == 404  # payments aren't visible to site staff


async def test_generated_documents_appear_in_the_folder(login_as, case):
    fin, _, _ = await test_ledger.generated(login_as, case)
    pse, _ = await login_as(Role.postsales_exec)
    await pse.post(
        f"/api/post-sales/cases/{case}/kyc",
        data={"doc_type": "pan"},
        files={"file": ("pan.png", PNG + b"\x07" * 50, "image/png")},
    )
    data = await folder(fin, case)
    assert any(s["kind"] == "Statement" and s["category"] == "payments" for s in data["system"])
    assert not any(s["category"] == "kyc" for s in data["system"])  # finance doesn't see KYC
    data = await folder(pse, case)
    assert any(s["kind"] == "KYC document" for s in data["system"])
    assert next(c for c in data["categories"] if c["key"] == "kyc")["count"] == 1
