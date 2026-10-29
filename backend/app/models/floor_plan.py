from sqlalchemy import BigInteger, CheckConstraint, Enum, ForeignKey, Identity, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.inventory import UnitType


class FloorPlan(TimestampMixin, Base):
    """A floor plan file for a project: for the whole project, one floor, or one unit type."""

    __tablename__ = "floor_plans"
    __table_args__ = (
        CheckConstraint("floor_id IS NULL OR unit_type IS NULL", name="floor_or_type_not_both"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    floor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("floors.id", ondelete="CASCADE"), index=True
    )
    unit_type: Mapped[UnitType | None] = mapped_column(
        Enum(
            UnitType,
            name="unit_type",
            create_type=False,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # under FILE_STORAGE_PATH/floor_plans
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
