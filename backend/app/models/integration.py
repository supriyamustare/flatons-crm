import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class IntegrationKind(enum.StrEnum):
    website = "website"
    portal_99acres = "99acres"
    magicbricks = "magicbricks"
    housing = "housing"
    facebook = "facebook"
    google_ads = "google_ads"


class InboundStatus(enum.StrEnum):
    created = "created"  # a new lead was made
    merged = "merged"  # added to an existing lead with the same phone number
    duplicate = "duplicate"  # the same enquiry delivered again (platform retry); ignored
    test = "test"  # checked only, no lead made
    pending = "pending"  # waiting to fetch details (Facebook)
    rejected = "rejected"  # couldn't be used, e.g. no valid phone number
    failed = "failed"  # an error while processing; see `error`


class Integration(TimestampMixin, Base):
    """A connection that sends enquiries into the CRM (a portal, ad platform or website form)."""

    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    kind: Mapped[IntegrationKind] = mapped_column(
        Enum(
            IntegrationKind, name="integration_kind", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
    )
    # SHA-256 of the secret key; the key itself is shown once and never stored
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Facebook only: app secret and page access token, encrypted with a key derived from SECRET_KEY
    fb_app_secret_enc: Mapped[str | None] = mapped_column(Text)
    fb_page_token_enc: Mapped[str | None] = mapped_column(Text)
    default_campaign_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    default_project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    received_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class InboundEvent(Base):
    """Every request a connection receives, kept with its raw contents for troubleshooting."""

    __tablename__ = "inbound_events"
    __table_args__ = (
        # A platform retrying the same enquiry is recognised by its own id and stored once
        UniqueConstraint(
            "integration_id", "external_id", name="uq_inbound_events_integration_external"
        ),
        Index("ix_inbound_events_integration_received", "integration_id", "received_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    integration_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[InboundStatus] = mapped_column(
        Enum(InboundStatus, name="inbound_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    lead_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(String(300))

    integration: Mapped[Integration] = relationship(lazy="selectin")
