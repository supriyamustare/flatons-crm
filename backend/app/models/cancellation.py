"""Stage 16: a controlled cancellation. Nothing is erased; every step is recorded."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Cancellation(TimestampMixin, Base):
    __tablename__ = "cancellations"
    __table_args__ = (
        Index(
            "uq_cancellations_live_case",
            "case_id",
            unique=True,
            postgresql_where=text("status NOT IN ('withdrawn', 'rejected')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # requested -> reviewed -> settlement_proposed -> approved -> communicated -> released / refund steps -> closed (or withdrawn / rejected)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="requested")
    initiated_by: Mapped[str] = mapped_column(String(20), nullable=False)  # customer / developer
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    contract_clause: Mapped[str | None] = mapped_column(String(200))
    supporting_document_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    requested_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    legal_review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {by, by_name, at, note}
    commercial_review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    settlement: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # snapshot, deductions, refund, balance due, prepared by
    approvals: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )  # [{kind: finance|management, by, by_name, at, note}]
    communication: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {on, via, by_name}
    refund_bank: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # payee, bank, account_enc, ifsc, method, entered/verified by
    refund_payment: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # paid_on, amount, utr, processed / reconciled by
    release: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # unit release approval {by, by_name, at}
    end_reason: Mapped[str | None] = mapped_column(String(1000))  # why withdrawn / rejected
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
