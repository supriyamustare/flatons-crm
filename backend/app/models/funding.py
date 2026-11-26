"""OCR (own contribution required): the customer's own share of the cost as a fixed amount; the rest is the home loan."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FundingPlan(TimestampMixin, Base):
    __tablename__ = "funding_plans"
    __table_args__ = (CheckConstraint("own_amount > 0", name="own_positive"),)

    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="CASCADE"), primary_key=True
    )
    own_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )  # rupees the customer pays from own funds
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="draft"
    )  # draft / approved
    entered_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    history: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )  # earlier approved amounts, with who, when and why
