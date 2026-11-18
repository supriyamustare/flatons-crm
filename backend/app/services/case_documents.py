"""Who may upload, review and see each category of the customer folder, and the system documents that appear in it."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_document import DocCategory as C
from app.models.demand import Demand, DemandStatus
from app.models.payment import Receipt, ReceiptStatus
from app.models.postsales import KycDocument, KycStatus
from app.models.user import KYC_VIEWERS, LEDGER_VIEWERS, POSTSALES_ROLES, Role

LABELS = {
    C.booking: "01 Booking & Application",
    C.kyc: "02 KYC & Customer Details",
    C.agreements: "03 Agreements & Legal",
    C.demands: "04 Demands & Invoices",
    C.payments: "05 Payments & Receipts",
    C.loan: "06 Home Loan & Bank",
    C.construction: "07 Construction Updates",
    C.correspondence: "08 Customer Correspondence",
    C.possession: "09 Possession & Handover",
    C.warranties: "10 Warranties & Defects",
    C.other: "11 Other Project Documents",
}
CORE = (Role.admin, Role.crm_manager, Role.postsales_exec)
FINANCE_CATS = (C.demands, C.payments, C.loan)

# Who may see a category (KYC and money stay with the people who already see them)
VIEW = (
    {c: tuple(POSTSALES_ROLES) for c in C}
    | {C.kyc: tuple(KYC_VIEWERS)}
    | {c: tuple(LEDGER_VIEWERS) for c in FINANCE_CATS}
)
# Who may upload into a category
UPLOAD = {
    C.booking: CORE,
    C.kyc: CORE,
    C.agreements: (*CORE, Role.legal),
    C.demands: (Role.admin, Role.finance, Role.crm_manager),
    C.payments: (Role.admin, Role.finance, Role.crm_manager),
    C.loan: (*CORE, Role.finance),
    C.construction: (Role.admin, Role.crm_manager, Role.project_manager, Role.site),
    C.correspondence: (*CORE, Role.legal, Role.service),
    C.possession: (Role.admin, Role.crm_manager, Role.site),
    C.warranties: (Role.admin, Role.crm_manager, Role.site, Role.after_sales),
    C.other: (*CORE, Role.legal, Role.project_manager),
}
# Who may verify and approve (never the uploader)
REVIEW = (
    {c: (Role.admin, Role.crm_manager) for c in C}
    | {C.agreements: (Role.admin, Role.crm_manager, Role.legal)}
    | {c: (Role.admin, Role.finance_approver) for c in FINANCE_CATS}
)
# Who may release to the customer or withdraw
RELEASE = (Role.admin, Role.crm_manager)


async def system_documents(db: AsyncSession, case_id: int, role: Role) -> list[dict]:
    """Documents the CRM itself produced or already holds, shown in the right folder (not stored twice)."""
    out = []
    if role in VIEW[C.kyc]:
        for k in await db.scalars(
            select(KycDocument).where(
                KycDocument.case_id == case_id, KycDocument.status != KycStatus.superseded
            )
        ):
            out.append(
                {
                    "category": C.kyc,
                    "title": k.doc_type.value.replace("_", " ").capitalize(),
                    "kind": "KYC document",
                    "number": None,
                    "date": k.uploaded_at.date().isoformat(),
                    "status": k.status.value,
                    "url": f"/api/post-sales/kyc/{k.id}/file",
                }
            )
    if role in VIEW[C.demands]:
        for d in await db.scalars(
            select(Demand).where(
                Demand.case_id == case_id,
                Demand.status.in_([DemandStatus.issued, DemandStatus.cancelled]),
            )
        ):
            no = f"DMD-{d.id:05d}" + (f" v{d.version}" if d.version > 1 else "")
            out.append(
                {
                    "category": C.demands,
                    "title": f"Demand letter: {d.stage_name}",
                    "kind": "Demand letter",
                    "number": no,
                    "date": d.demanded_on.isoformat(),
                    "status": d.status.value,
                    "url": f"/demand-letter/{case_id}/{d.id}",
                }
            )
    if role in VIEW[C.payments]:
        for r in await db.scalars(
            select(Receipt).where(
                Receipt.case_id == case_id, Receipt.status == ReceiptStatus.confirmed
            )
        ):
            out.append(
                {
                    "category": C.payments,
                    "title": f"Receipt Rs {r.amount:,}",
                    "kind": "Receipt",
                    "number": f"RCT-{r.id:05d}",
                    "date": r.received_on.isoformat(),
                    "status": "confirmed",
                    "url": f"/statement/{case_id}",
                }
            )
        out.append(
            {
                "category": C.payments,
                "title": "Statement of account (always current)",
                "kind": "Statement",
                "number": None,
                "date": None,
                "status": "live",
                "url": f"/statement/{case_id}",
            }
        )
    return out
