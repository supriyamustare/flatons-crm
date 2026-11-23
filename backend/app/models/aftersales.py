"""Stage 15: warranty catalogue (per project), defect register, and the maintenance / facility-management handover."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WarrantyItem(Base):
    """One warranty or defect-liability term for a project, set from the contract, product warranty or law."""

    __tablename__ = "warranty_items"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(
        String(150), nullable=False
    )  # e.g. "Structural defects", "Waterproofing", "Sanitary fittings (Jaquar)"
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(
        String(150)
    )  # developer / contractor / manufacturer name
    period_months: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_from: Mapped[str] = mapped_column(
        String(20), nullable=False, default="possession"
    )  # possession / completion / purchase
    basis: Mapped[str | None] = mapped_column(
        String(300)
    )  # contract clause, product warranty card, law
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class Defect(TimestampMixin, Base):
    __tablename__ = "defects"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    case_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="RESTRICT"), index=True
    )  # none = common area
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="raised")
    complaint_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="phone")
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    item: Mapped[str | None] = mapped_column(String(150))  # product, fixture or equipment
    warranty_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warranty_items.id", ondelete="SET NULL")
    )
    warranty_start: Mapped[date | None] = mapped_column(Date)
    warranty_end: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    raised_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # workflow details: {acknowledged, inspection{visit_at, availability}, diagnosis{visited_on, text}, responsibility{party, covered, reason, estimate},
    # customer_approval{approved, on}, rectification{action, contractor, materials, target}, completed{work, by, at}, quality{by, at}, customer{response, note}}
    steps: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    target_date: Mapped[date | None] = mapped_column(Date)
    reopened_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    closure_reason: Mapped[str | None] = mapped_column(String(500))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminded_on: Mapped[date | None] = mapped_column(Date)


class DefectFile(Base):
    __tablename__ = "defect_files"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    defect_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("defects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # complaint / diagnosis / completion / not_covered
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # under FILE_STORAGE_PATH/defects
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FacilityHandover(Base):
    """C. Maintenance and facility-management handover, one per project (kept apart from society accounting)."""

    __tablename__ = "facility_handovers"

    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
