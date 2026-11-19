"""The sale agreement for a case: from initiation through review, execution and registration to release."""

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AgreementStatus(enum.StrEnum):
    initiated = "initiated"
    data_verified = "data_verified"
    drafted = "drafted"
    internal_review = "internal_review"
    changes_requested = "changes_requested"
    customer_review = "customer_review"
    execution_prep = "execution_prep"
    registered = "registered"
    final_uploaded = "final_uploaded"
    cancelled = "cancelled"


class Agreement(TimestampMixin, Base):
    __tablename__ = "agreements"
    __table_args__ = (
        Index(
            "uq_agreements_live_case",
            "case_id",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)", name="cancel_needs_reason"
        ),
        CheckConstraint(
            "stamp_duty_amount IS NULL OR stamp_duty_amount >= 0", name="stamp_not_negative"
        ),
        CheckConstraint(
            "registration_fee_amount IS NULL OR registration_fee_amount >= 0",
            name="fee_not_negative",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[AgreementStatus] = mapped_column(
        Enum(
            AgreementStatus, name="agreement_status", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        default=AgreementStatus.initiated,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # draft version (0 = no draft yet)
    draft: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # the current draft, frozen per version
    initiated_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    drafted_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    legal_approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    legal_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finance_approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    finance_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changes_note: Mapped[str | None] = mapped_column(
        String(1000)
    )  # what must change (internal or customer)
    shared_on: Mapped[date | None] = mapped_column(Date)
    share_method: Mapped[str | None] = mapped_column(String(40))
    customer_accepted_on: Mapped[date | None] = mapped_column(Date)
    # Execution preparation
    stamp_duty_amount: Mapped[int | None] = mapped_column(BigInteger)
    stamp_duty_paid_on: Mapped[date | None] = mapped_column(Date)
    stamp_duty_ref: Mapped[str | None] = mapped_column(String(80))
    registration_fee_amount: Mapped[int | None] = mapped_column(BigInteger)
    registration_fee_paid_on: Mapped[date | None] = mapped_column(Date)
    registration_fee_ref: Mapped[str | None] = mapped_column(String(80))
    appointment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sro_office: Mapped[str | None] = mapped_column(String(150))  # sub-registrar office
    id_docs_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    signing_note: Mapped[str | None] = mapped_column(Text)
    # Signing and registration
    executed_on: Mapped[date | None] = mapped_column(Date)
    registration_no: Mapped[str | None] = mapped_column(String(80))
    registered_on: Mapped[date | None] = mapped_column(Date)
    final_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("case_documents.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
