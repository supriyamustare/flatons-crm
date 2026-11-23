"""Stage 17: one notification engine for customer communication: approved, versioned templates and a message log."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CommTemplate(Base):
    __tablename__ = "comm_templates"
    __table_args__ = (
        Index(
            "uq_comm_template_approved",
            "event",
            "channel",
            text("coalesce(project_id, 0)"),
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # email / sms / whatsapp
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE")
    )  # none = every project
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    language: Mapped[str] = mapped_column(
        String(30), nullable=False, default="English", server_default=text("'English'")
    )
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )  # contractual notice: a channel opt-out doesn't stop it
    delay_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 0 = immediate; otherwise scheduled
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="draft"
    )  # draft / approved / retired
    author_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )  # none = starting draft
    approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CommMessage(Base):
    """Every customer message: what was sent, to whom, how, and what happened (the communication history)."""

    __tablename__ = "comm_messages"
    __table_args__ = (Index("ix_comm_messages_due", "status", "send_after"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    template_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comm_templates.id", ondelete="SET NULL")
    )
    template_version: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(254))
    recipient_name: Mapped[str | None] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # queued / held / sent / failed / skipped
    reason: Mapped[str | None] = mapped_column(String(500))  # failure, hold or skip reason
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    send_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
