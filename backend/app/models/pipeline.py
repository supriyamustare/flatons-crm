from sqlalchemy import CheckConstraint, Enum, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.lead import LeadStatus

# Starting probabilities (percent chance a lead in this stage becomes a booking).
# Admins can change them; these are only the defaults put in by the migration.
DEFAULT_PROBABILITIES: dict[LeadStatus, int] = {
    LeadStatus.new: 5,
    LeadStatus.not_reachable: 2,
    LeadStatus.contacted: 10,
    LeadStatus.qualified: 20,
    LeadStatus.follow_up: 15,
    LeadStatus.visit_scheduled: 30,
    LeadStatus.visit_done: 40,
    LeadStatus.revisit: 50,
    LeadStatus.negotiation: 70,
    LeadStatus.on_hold: 10,
    LeadStatus.booked: 100,
    LeadStatus.lost: 0,
    LeadStatus.junk: 0,
}


class PipelineStage(TimestampMixin, Base):
    """One row per lead status, holding the probability used for the weighted forecast."""

    __tablename__ = "pipeline_stages"
    __table_args__ = (
        CheckConstraint("probability_pct BETWEEN 0 AND 100", name="probability_range"),
    )

    stage: Mapped[LeadStatus] = mapped_column(
        Enum(
            LeadStatus,
            name="lead_status",
            create_type=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        primary_key=True,
    )
    probability_pct: Mapped[int] = mapped_column(Integer, nullable=False)
