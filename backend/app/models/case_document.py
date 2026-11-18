"""The customer folder: every document for a case, classified, versioned, reviewed and released."""

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class DocCategory(enum.StrEnum):
    booking = "booking"  # 01 Booking & Application
    kyc = "kyc"  # 02 KYC & Customer Details
    agreements = "agreements"  # 03 Agreements & Legal
    demands = "demands"  # 04 Demands & Invoices
    payments = "payments"  # 05 Payments & Receipts
    loan = "loan"  # 06 Home Loan & Bank
    construction = "construction"  # 07 Construction Updates
    correspondence = "correspondence"  # 08 Customer Correspondence
    possession = "possession"  # 09 Possession & Handover
    warranties = "warranties"  # 10 Warranties & Defects
    other = "other"  # 11 Other Project Documents


class Verification(enum.StrEnum):
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


class Approval(enum.StrEnum):
    under_approval = "under_approval"
    approved = "approved"
    released = "released"  # visible to the customer
    withdrawn = "withdrawn"
    rejected = "rejected"  # kept in the history; never shown as approved


class Visibility(enum.StrEnum):
    internal = "internal"
    customer = "customer"


class CaseDocument(Base):
    __tablename__ = "case_documents"
    __table_args__ = (
        CheckConstraint(
            "(approval = 'released') = (visibility = 'customer')", name="released_means_customer"
        ),
        CheckConstraint(
            "version = 1 OR (supersedes_id IS NOT NULL AND version_reason IS NOT NULL)",
            name="new_version_has_reason",
        ),
        CheckConstraint(
            "approval NOT IN ('rejected', 'withdrawn') OR status_reason IS NOT NULL",
            name="reject_withdraw_reason",
        ),
        Index("uq_case_documents_file", "case_id", "sha256", unique=True),
        Index(
            "uq_case_documents_number",
            "case_id",
            "category",
            text("upper(doc_number)"),
            unique=True,
            postgresql_where=text(
                "doc_number IS NOT NULL AND superseded_by_id IS NULL AND approval NOT IN ('rejected', 'withdrawn')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category: Mapped[DocCategory] = mapped_column(
        _enum(DocCategory, "doc_category"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(
        String(120), nullable=False
    )  # specific type, e.g. "Allotment letter"
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_number: Mapped[str | None] = mapped_column(String(80))
    doc_date: Mapped[date | None] = mapped_column(Date)  # date of issue or execution
    expiry_date: Mapped[date | None] = mapped_column(Date)
    linked_ref: Mapped[str | None] = mapped_column(
        String(80)
    )  # demand / receipt / agreement / request reference
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # under FILE_STORAGE_PATH/case_docs
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verification: Mapped[Verification] = mapped_column(
        _enum(Verification, "doc_verification"), nullable=False, default=Verification.pending
    )
    approval: Mapped[Approval] = mapped_column(
        _enum(Approval, "doc_approval"), nullable=False, default=Approval.under_approval
    )
    visibility: Mapped[Visibility] = mapped_column(
        _enum(Visibility, "doc_visibility"), nullable=False, default=Visibility.internal
    )
    status_reason: Mapped[str | None] = mapped_column(String(500))  # why rejected / withdrawn
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("case_documents.id", ondelete="SET NULL")
    )
    superseded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("case_documents.id", ondelete="SET NULL")
    )
    version_reason: Mapped[str | None] = mapped_column(String(500))
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
