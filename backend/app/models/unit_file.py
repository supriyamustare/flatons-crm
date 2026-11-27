"""Files attached to a flat (unit), e.g. a signed cost sheet or a drawing."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UnitFile(Base):
    __tablename__ = "unit_files"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # under FILE_STORAGE_PATH/unit_files
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
