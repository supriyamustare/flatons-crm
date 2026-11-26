"""Home loan coordination: the lender, documents the bank asks for, and each disbursement."""

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
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class VerificationState(enum.StrEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    query = "query"  # the bank raised a query
    cleared = "cleared"
    rejected = "rejected"


class DisbursementStatus(enum.StrEnum):
    requested = "requested"  # request sent to the bank
    awaited = "awaited"  # bank acknowledged; expected date given
    received = "received"  # funds arrived; receipt recorded (waiting for confirmation)
    cancelled = "cancelled"


class Loan(TimestampMixin, Base):
    __tablename__ = "loans"
    __table_args__ = (
        Index(
            "uq_loans_live_case", "case_id", unique=True, postgresql_where=text("closed_at IS NULL")
        ),
        CheckConstraint("applied_amount IS NULL OR applied_amount > 0", name="applied_positive"),
        CheckConstraint(
            "sanctioned_amount IS NULL OR sanctioned_amount > 0", name="sanctioned_positive"
        ),
        CheckConstraint("(closed_at IS NULL) = (close_reason IS NULL)", name="close_needs_reason"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    lender: Mapped[str] = mapped_column(String(150), nullable=False)
    application_no: Mapped[str | None] = mapped_column(String(80))
    consent_on: Mapped[date | None] = mapped_column(
        Date
    )  # customer's consent for us to coordinate with the bank
    consent_recorded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    applied_amount: Mapped[int | None] = mapped_column(BigInteger)
    sanctioned_amount: Mapped[int | None] = mapped_column(BigInteger)
    sanction_date: Mapped[date | None] = mapped_column(Date)
    sanction_valid_until: Mapped[date | None] = mapped_column(Date)
    sanction_letter_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("case_documents.id", ondelete="SET NULL")
    )  # the bank's sanction letter
    rm_name: Mapped[str | None] = mapped_column(String(150))  # bank relationship manager
    rm_phone: Mapped[str | None] = mapped_column(String(20))
    rm_email: Mapped[str | None] = mapped_column(String(254))
    technical_status: Mapped[VerificationState] = mapped_column(
        _enum(VerificationState, "loan_verification"),
        nullable=False,
        default=VerificationState.not_started,
    )
    legal_status: Mapped[VerificationState] = mapped_column(
        _enum(VerificationState, "loan_verification"),
        nullable=False,
        default=VerificationState.not_started,
    )
    pending_conditions: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )  # follow-up owner
    next_follow_up_on: Mapped[date | None] = mapped_column(Date, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(500))

    doc_requests: Mapped[list["LoanDocRequest"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="LoanDocRequest.id"
    )
    disbursements: Mapped[list["Disbursement"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="Disbursement.id"
    )


class LoanDocRequest(Base):
    __tablename__ = "loan_doc_requests"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    loan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    submitted_on: Mapped[date | None] = mapped_column(Date)
    submitted_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    case_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("case_documents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Disbursement(TimestampMixin, Base):
    __tablename__ = "loan_disbursements"
    __table_args__ = (
        CheckConstraint("expected_amount > 0", name="expected_positive"),
        CheckConstraint("actual_amount IS NULL OR actual_amount > 0", name="actual_positive"),
        CheckConstraint(
            "status <> 'received' OR (actual_amount IS NOT NULL AND actual_date IS NOT NULL AND utr IS NOT NULL)",
            name="received_complete",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    loan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_no: Mapped[str | None] = mapped_column(String(80))
    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    for_stage: Mapped[str | None] = mapped_column(String(120))  # e.g. "Plinth" or a demand number
    expected_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[DisbursementStatus] = mapped_column(
        _enum(DisbursementStatus, "disbursement_status"),
        nullable=False,
        default=DisbursementStatus.requested,
    )
    delay_reason: Mapped[str | None] = mapped_column(String(500))
    actual_date: Mapped[date | None] = mapped_column(Date)
    actual_amount: Mapped[int | None] = mapped_column(BigInteger)
    utr: Mapped[str | None] = mapped_column(String(60))
    receipt_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("receipts.id", ondelete="SET NULL")
    )
    delay_notified_on: Mapped[date | None] = mapped_column(Date)
