"""Post-sales: a case per booking, the customer master (profile, co-applicants, nominee, consents) and KYC."""

import enum
from datetime import date, datetime
from decimal import Decimal
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
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.booking import Booking
from app.models.user import User


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class CaseStatus(enum.StrEnum):
    handover_pending = "handover_pending"  # waiting for post-sales to check and accept
    returned_to_sales = "returned_to_sales"  # sent back with a reason; sales corrects and resends
    accepted = "accepted"  # post-sales owns the customer from here
    cancelled = "cancelled"  # the booking was cancelled


class OnboardingStatus(enum.StrEnum):
    not_started = "not_started"
    otp_verification = "otp_verification"  # used once the customer portal exists
    documents_pending = "documents_pending"
    under_review = "under_review"
    clarification_required = "clarification_required"
    approved = "approved"


class OwnershipType(enum.StrEnum):
    individual = "individual"
    joint = "joint"
    company = "company"
    partnership = "partnership"
    huf = "huf"
    trust = "trust"
    other = "other"


ENTITY_OWNERSHIP = (
    OwnershipType.company,
    OwnershipType.partnership,
    OwnershipType.huf,
    OwnershipType.trust,
    OwnershipType.other,
)


class KycDocType(enum.StrEnum):
    pan = "pan"
    aadhaar = "aadhaar"
    passport = "passport"
    voter_id = "voter_id"
    driving_licence = "driving_licence"
    address_proof = "address_proof"  # utility bill, bank statement, rent agreement
    photo = "photo"
    entity_pan = "entity_pan"
    registration_certificate = (
        "registration_certificate"  # incorporation / partnership deed / trust deed
    )
    board_resolution = "board_resolution"  # or authority letter
    other = "other"


class KycStatus(enum.StrEnum):
    pending = "pending"  # uploaded, waiting for review
    verified = "verified"
    rejected = "rejected"
    expired = "expired"
    superseded = "superseded"  # replaced by a newer upload (kept for history)


class PostSalesCase(TimestampMixin, Base):
    __tablename__ = "postsales_cases"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    status: Mapped[CaseStatus] = mapped_column(
        _enum(CaseStatus, "case_status"), nullable=False, default=CaseStatus.handover_pending
    )
    onboarding_status: Mapped[OnboardingStatus] = mapped_column(
        _enum(OnboardingStatus, "onboarding_status"),
        nullable=False,
        default=OnboardingStatus.not_started,
    )
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    accepted_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_reason: Mapped[str | None] = mapped_column(String(500))
    clarification_reason: Mapped[str | None] = mapped_column(String(500))

    booking: Mapped[Booking] = relationship(lazy="selectin")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id], lazy="selectin")


class CustomerProfile(TimestampMixin, Base):
    """The primary purchaser (or the entity, with its authorized signatory as the person)."""

    __tablename__ = "customer_profiles"
    __table_args__ = (
        CheckConstraint(
            "ownership_pct IS NULL OR (ownership_pct > 0 AND ownership_pct <= 100)",
            name="ownership_pct_range",
        ),
    )

    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="CASCADE"), primary_key=True
    )
    ownership_type: Mapped[OwnershipType] = mapped_column(
        _enum(OwnershipType, "ownership_type"), nullable=False, default=OwnershipType.individual
    )
    legal_name: Mapped[str | None] = mapped_column(String(200))  # as on PAN
    entity_name: Mapped[str | None] = mapped_column(String(200))  # company / firm / HUF / trust
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    pan: Mapped[str | None] = mapped_column(String(10))
    ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    mobile: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    correspondence_address: Mapped[str | None] = mapped_column(Text)
    permanent_address: Mapped[str | None] = mapped_column(Text)
    preferred_language: Mapped[str | None] = mapped_column(String(40))
    contact_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    contact_sms: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    contact_whatsapp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    communication_needs: Mapped[str | None] = mapped_column(
        String(300)
    )  # accessibility or other needs
    consent_portal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_electronic_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_data_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nominee_name: Mapped[str | None] = mapped_column(String(150))
    nominee_relation: Mapped[str | None] = mapped_column(String(60))
    nominee_mobile: Mapped[str | None] = mapped_column(String(20))


class CoApplicant(TimestampMixin, Base):
    __tablename__ = "co_applicants"
    __table_args__ = (
        CheckConstraint(
            "ownership_pct IS NULL OR (ownership_pct > 0 AND ownership_pct < 100)",
            name="ownership_pct_range",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    relation: Mapped[str | None] = mapped_column(String(60))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    pan: Mapped[str | None] = mapped_column(String(10))
    mobile: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class KycDocument(Base):
    """One uploaded KYC file. A new upload of the same type for the same person supersedes the old one."""

    __tablename__ = "kyc_documents"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    co_applicant_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("co_applicants.id", ondelete="CASCADE")
    )  # None = primary
    doc_type: Mapped[KycDocType] = mapped_column(_enum(KycDocType, "kyc_doc_type"), nullable=False)
    status: Mapped[KycStatus] = mapped_column(
        _enum(KycStatus, "kyc_status"), nullable=False, default=KycStatus.pending
    )
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)  # file integrity
    expiry_date: Mapped[date | None] = mapped_column(Date)
    review_note: Mapped[str | None] = mapped_column(String(500))  # rejection reason
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
    superseded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("kyc_documents.id", ondelete="SET NULL")
    )


class CaseEvent(Base):
    """Case history: every handover, onboarding and KYC decision with who, when and why."""

    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    actor: Mapped[User | None] = relationship(lazy="selectin")
