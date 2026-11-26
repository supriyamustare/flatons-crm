from datetime import timedelta

from sqlalchemy import select

from app.models import Role
from app.models.case_document import CaseDocument
from app.models.ledger import Ledger
from app.services import ledger as ledger_svc
from tests import test_ledger
from tests.test_demands import approved_ledger
from tests.test_ledger import PAID, TODAY
from tests.test_loans import LOAN, loan, sanctioned
from tests.test_payments import rec

case = test_ledger.case
PDF = b"%PDF-1.4\nsanction"


async def total_payable(db, case_id) -> int:
    """What the loan can fund: the agreement value with GST (stamp duty and other charges are the customer's own)."""
    led = await db.scalar(select(Ledger).where(Ledger.case_id == case_id))
    await db.refresh(led)
    t = ledger_svc.totals(led)
    return t.schedule_amount + t.schedule_gst


async def test_plan_is_maker_checker_and_changes_keep_history(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    r = await pse.put(f"/api/post-sales/cases/{case}/ocr", json={"own_amount": 400_000})
    assert r.status_code == 422 and "ledger first" in r.text
    fin, chk = await approved_ledger(login_as, case)
    total = await total_payable(db, case)
    assert (
        await pse.put(f"/api/post-sales/cases/{case}/ocr", json={"own_amount": total + 1})
    ).status_code == 422
    site, _ = await login_as(Role.site)
    assert (
        await site.put(f"/api/post-sales/cases/{case}/ocr", json={"own_amount": 400_000})
    ).status_code == 403
    s = (
        await pse.put(
            f"/api/post-sales/cases/{case}/ocr",
            json={"own_amount": 400_000, "note": "10% from savings"},
        )
    ).json()
    assert (
        s["plan"]["status"] == "draft"
        and s["loan_needed"] == total - 400_000
        and s["own_required"] == 400_000
    )
    admin, _ = await login_as(Role.admin)
    assert (
        await pse.post(f"/api/post-sales/cases/{case}/ocr/approve")
    ).status_code == 403  # not a finance approver
    s = (await chk.post(f"/api/post-sales/cases/{case}/ocr/approve")).json()
    assert s["plan"]["status"] == "approved" and s["plan"]["approved_by"]
    r = await pse.put(f"/api/post-sales/cases/{case}/ocr", json={"own_amount": 500_000})
    assert r.status_code == 422 and "reason" in r.text
    s = (
        await pse.put(
            f"/api/post-sales/cases/{case}/ocr",
            json={"own_amount": 500_000, "reason": "Customer selling a plot; loan reduced"},
        )
    ).json()
    assert (
        s["plan"]["status"] == "draft"
        and s["plan"]["history"][0]["own_amount"] == 400_000
        and s["plan"]["history"][0]["reason"].startswith("Customer selling")
    )
    s = (
        await admin.post(f"/api/post-sales/cases/{case}/ocr/approve")
    ).json()  # admins approve too, but never their own entry
    assert s["plan"]["status"] == "approved"
    await admin.put(
        f"/api/post-sales/cases/{case}/ocr", json={"own_amount": 450_000, "reason": "Correction"}
    )
    assert (await admin.post(f"/api/post-sales/cases/{case}/ocr/approve")).status_code == 403


async def test_split_receipts_and_bank_shortfall(login_as, db, case):
    fin, chk = await approved_ledger(login_as, case)
    total = await total_payable(db, case)
    pse, _ = await login_as(Role.postsales_exec)
    s = (await pse.put(f"/api/post-sales/cases/{case}/ocr", json={"own_amount": 400_000})).json()
    st = s["stages"]
    assert (
        st[0]["own_part"] == st[0]["amount"] and st[0]["loan_part"] == 0
    )  # the booking stage is the customer's own
    assert (
        sum(x["own_part"] for x in st) == 400_000
        and sum(x["loan_part"] for x in st) == total - 400_000
    )
    assert (
        s["pending_own"] == PAID and s["received_own"] == 0
    )  # the booking receipt waits for confirmation
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    s = (await pse.get(f"/api/post-sales/cases/{case}/ocr")).json()
    assert s["received_own"] == PAID and s["remaining_own"] == 400_000 - PAID
    await sanctioned(login_as, case)  # the bank approves Rs 25,00,000
    s = (await pse.get(f"/api/post-sales/cases/{case}/ocr")).json()
    needed = total - 400_000
    assert (
        s["sanctioned"] == 2_500_000
        and s["shortfall"] == needed - 2_500_000
        and s["own_required"] == 400_000 + s["shortfall"]
    )
    assert any("must pay" in w for w in s["warnings"])
    _ = rec


async def test_sanction_letter_on_the_loan_tab(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    r = await pse.post(
        f"/api/post-sales/cases/{case}/loan/sanction-letter",
        data={"sanctioned_amount": "2500000", "sanction_date": TODAY.isoformat()},
        files={"file": ("sanction.pdf", PDF, "application/pdf")},
    )
    assert r.status_code == 422 and "Record the loan first" in r.text
    await loan(pse, case, consent_on=TODAY.isoformat())
    bad = await pse.post(
        f"/api/post-sales/cases/{case}/loan/sanction-letter",
        data={
            "sanctioned_amount": "2500000",
            "sanction_date": TODAY.isoformat(),
            "valid_until": (TODAY - timedelta(days=1)).isoformat(),
        },
        files={"file": ("s.pdf", PDF, "application/pdf")},
    )
    assert bad.status_code == 422
    s = (
        await pse.post(
            f"/api/post-sales/cases/{case}/loan/sanction-letter",
            data={
                "sanctioned_amount": "2500000",
                "sanction_date": TODAY.isoformat(),
                "valid_until": (TODAY + timedelta(days=180)).isoformat(),
            },
            files={"file": ("sanction.pdf", PDF, "application/pdf")},
        )
    ).json()
    sl = s["sanction_letter"]
    assert (
        sl["sanctioned_amount"] == 2_500_000
        and sl["title"] == f"Loan sanction letter: {LOAN['lender']}"
        and s["loan"]["sanctioned_amount"] == 2_500_000
    )
    d1 = await db.get(CaseDocument, sl["id"])
    assert d1.category.value == "loan" and d1.doc_type == "Bank sanction letter" and d1.version == 1
    s = (
        await pse.post(
            f"/api/post-sales/cases/{case}/loan/sanction-letter",
            data={"sanctioned_amount": "2600000", "sanction_date": TODAY.isoformat()},
            files={"file": ("sanction-revised.pdf", PDF + b" revised", "application/pdf")},
        )
    ).json()
    d2 = await db.get(CaseDocument, s["sanction_letter"]["id"])
    assert (
        d2.id != d1.id
        and d2.version == 2
        and s["sanction_letter"]["sanctioned_amount"] == 2_600_000
    )  # a new version, not a second document
