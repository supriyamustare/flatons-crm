"""Nightly snapshots of the headline MIS figures, so past positions can be seen as they were."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MisSnapshot(Base):
    __tablename__ = "mis_snapshots"
    __table_args__ = (
        Index(
            "uq_mis_snapshot_day_project", "taken_on", text("coalesce(project_id, 0)"), unique=True
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    taken_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE")
    )  # none = all projects
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
