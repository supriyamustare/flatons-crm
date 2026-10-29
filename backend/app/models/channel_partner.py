from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ChannelPartner(TimestampMixin, Base):
    """A broker or agency that brings customers. Leads and bookings point to the partner who brought them."""

    __tablename__ = "channel_partners"
    __table_args__ = (
        # One partner per mobile number and per RERA number (RERA is optional)
        Index("uq_channel_partners_mobile", "mobile", unique=True),
        Index(
            "uq_channel_partners_rera",
            "rera_number",
            unique=True,
            postgresql_where=text("rera_number IS NOT NULL"),
        ),
        Index("ix_channel_partners_name", "name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(150))
    mobile: Mapped[str] = mapped_column(String(20), nullable=False)  # E.164, e.g. +919876543210
    email: Mapped[str | None] = mapped_column(String(254))
    rera_number: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
