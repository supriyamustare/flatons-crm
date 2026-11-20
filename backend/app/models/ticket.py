"""Customer service tickets: one place for every request or complaint, so customers never repeat themselves."""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class TicketCategory(enum.StrEnum):
    payment = "payment"  # payment or ledger clarification
    receipt = "receipt"  # receipt not available
    demand = "demand"  # demand discrepancy
    agreement = "agreement"  # agreement or registration query
    kyc = "kyc"  # KYC or profile correction
    loan = "loan"  # loan or bank documentation
    document = "document"  # document download request
    construction = "construction"  # construction update enquiry
    modification = "modification"  # modification or change request
    parking = "parking"  # parking or unit allocation query
    possession = "possession"  # possession readiness
    snagging = "snagging"  # inspection and snagging
    defect = "defect"  # defect or warranty complaint
    refund = "refund"  # refund or cancellation
    grievance = "grievance"  # general customer grievance


class Priority(enum.StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"  # e.g. a safety-related defect


class Team(enum.StrEnum):
    crm = "crm"
    finance = "finance"
    legal = "legal"
    projects = "projects"  # project / site
    after_sales = "after_sales"


class TicketStatus(enum.StrEnum):
    raised = "raised"
    assigned = "assigned"
    acknowledged = "acknowledged"
    in_progress = "in_progress"
    waiting_customer = "waiting_customer"  # SLA paused
    waiting_internal = "waiting_internal"
    waiting_external = "waiting_external"  # third party; SLA paused
    resolution_proposed = "resolution_proposed"
    closed = "closed"


PAUSED = (TicketStatus.waiting_customer, TicketStatus.waiting_external)


class ClosureReason(enum.StrEnum):
    resolved = "resolved"
    duplicate = "duplicate"
    not_applicable = "not_applicable"  # not a valid request
    customer_withdrew = "customer_withdrew"
    no_response = "no_response"  # customer didn't respond after follow-ups
    transferred = "transferred"  # handled under another ticket / process


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "(status = 'closed') = (closure_reason IS NOT NULL AND closed_at IS NOT NULL)",
            name="closed_has_reason",
        ),
        CheckConstraint("csat IS NULL OR csat BETWEEN 1 AND 5", name="csat_range"),
        Index(
            "ix_tickets_open",
            "status",
            "resolution_due_at",
            postgresql_where=text("status <> 'closed'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category: Mapped[TicketCategory] = mapped_column(
        _enum(TicketCategory, "ticket_category"), nullable=False
    )
    subcategory: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="phone")
    priority: Mapped[Priority] = mapped_column(
        _enum(Priority, "ticket_priority"), nullable=False, default=Priority.normal
    )
    team: Mapped[Team] = mapped_column(_enum(Team, "ticket_team"), nullable=False)
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[TicketStatus] = mapped_column(
        _enum(TicketStatus, "ticket_status"), nullable=False, default=TicketStatus.raised
    )
    raised_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # SLA: response and resolution targets, set from the priority; resolution moves out while paused
    response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # first response
    paused_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_seconds_customer: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    paused_seconds_external: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # resolution proposed
    customer_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csat: Mapped[int | None] = mapped_column(Integer)  # 1-5
    csat_comment: Mapped[str | None] = mapped_column(String(1000))
    closure_reason: Mapped[ClosureReason | None] = mapped_column(
        _enum(ClosureReason, "closure_reason")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    escalation_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )  # part 2

    events: Mapped[list["TicketEvent"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="TicketEvent.id"
    )
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="TicketAttachment.id"
    )


class TicketEvent(Base):
    """Everything that happens on a ticket. Internal notes never reach the customer; messages are the customer log."""

    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # status, note, message_in, message_out, assigned, reopened, closed, ...
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    text_: Mapped[str | None] = mapped_column("text", Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # under FILE_STORAGE_PATH/tickets
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(20), nullable=False, default="evidence"
    )  # evidence (customer) / resolution
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
