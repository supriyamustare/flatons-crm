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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.project import Project
from app.models.user import User


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Channel(enum.StrEnum):
    google_ads = "google_ads"
    social = "social"  # Facebook / Instagram
    portal_99acres = "99acres"
    magicbricks = "magicbricks"
    housing = "housing"
    website = "website"
    print = "print"  # newspaper, hoarding, flyers
    event = "event"  # expo, site event
    sms_email = "sms_email"
    channel_partner = "channel_partner"
    other = "other"


class ExpenseCategory(enum.StrEnum):
    ad_spend = "ad_spend"
    agency_fee = "agency_fee"
    printing = "printing"
    event = "event"
    listing_fee = "listing_fee"
    other = "other"


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_in_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "campaign_channel"), nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )

    project: Mapped[Project | None] = relationship(lazy="selectin")


class Expense(Base):
    """Money spent on a campaign. Amounts are whole rupees."""

    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_expenses_campaign_spent_on", "campaign_id", "spent_on"),
        Index("ix_expenses_spent_on", "spent_on"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    spent_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[ExpenseCategory] = mapped_column(
        _enum(ExpenseCategory, "expense_category"), nullable=False
    )
    vendor: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(String(500))
    # Stored under FILE_STORAGE_PATH/receipts/; never served directly, only via the API.
    receipt_path: Mapped[str | None] = mapped_column(String(255))
    receipt_name: Mapped[str | None] = mapped_column(String(150))
    receipt_type: Mapped[str | None] = mapped_column(String(50))
    entered_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    campaign: Mapped[Campaign] = relationship(lazy="selectin")
    entered_by: Mapped[User | None] = relationship(lazy="selectin")
