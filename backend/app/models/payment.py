"""Receipts (payments received) and how each is matched to the ledger: stages of the payment plan or other charges.

Receipts are never deleted: a bounced or reversed receipt stays, with the reason, and simply stops counting."""

import enum
from datetime import date, datetime

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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.ledger import ChargeHead


def _enum(cls: type[enum.Enum], name: str, create: bool = True) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e], create_type=create)


class ReceiptMode(enum.StrEnum):
    cheque = "cheque"
    dd = "dd"  # demand draft
    neft = "neft"
    rtgs = "rtgs"
    imps = "imps"
    upi = "upi"
    card = "card"
    cash = "cash"
    other = "other"


BOUNCEABLE = (ReceiptMode.cheque, ReceiptMode.dd)


class FundSource(enum.StrEnum):
    own = "own"  # the customer's own funds
    loan = "loan"  # disbursed by the lender


class ReceiptStatus(enum.StrEnum):
    recorded = "recorded"  # entered by finance; waiting for a finance approver to confirm
    confirmed = "confirmed"  # verified; counts in the balances
    bounced = "bounced"  # cheque / DD returned unpaid
    reversed = "reversed"  # entered in error and reversed


LIVE = (ReceiptStatus.recorded, ReceiptStatus.confirmed)


class Receipt(TimestampMixin, Base):
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("mode = 'cash' OR reference IS NOT NULL", name="reference_unless_cash"),
        CheckConstraint("mode <> 'cash' OR amount < 200000", name="cash_under_2_lakh"),
        CheckConstraint(
            "(status IN ('bounced', 'reversed')) = (void_reason IS NOT NULL)",
            name="void_needs_reason",
        ),
        # The same cheque / UTR can't be live twice (a bounced cheque may be presented again)
        Index(
            "uq_receipts_live_reference",
            "mode",
            text("upper(reference)"),
            unique=True,
            postgresql_where=text("reference IS NOT NULL AND status IN ('recorded', 'confirmed')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # rupees
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[ReceiptMode] = mapped_column(_enum(ReceiptMode, "receipt_mode"), nullable=False)
    source: Mapped[FundSource] = mapped_column(
        _enum(FundSource, "fund_source"), nullable=False, default=FundSource.own
    )
    payer_name: Mapped[str | None] = mapped_column(String(150))
    reference: Mapped[str | None] = mapped_column(
        String(60)
    )  # cheque number / UTR / transaction id
    bank_name: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(String(500))
    from_booking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    status: Mapped[ReceiptStatus] = mapped_column(
        _enum(ReceiptStatus, "receipt_status"), nullable=False, default=ReceiptStatus.recorded
    )
    recorded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(500))

    allocations: Mapped[list["Allocation"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="Allocation.id"
    )


class Allocation(Base):
    """Part of a receipt applied to one stage (by its number in the schedule) or one charge head."""

    __tablename__ = "receipt_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("(stage_seq IS NULL) <> (charge_head IS NULL)", name="one_target"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_seq: Mapped[int | None] = mapped_column(Integer)
    charge_head: Mapped[ChargeHead | None] = mapped_column(
        _enum(ChargeHead, "charge_head", create=False)
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
