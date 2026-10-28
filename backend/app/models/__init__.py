"""Import every model here so Alembic autogenerate can see it."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.booking import Booking, BookingEvent, BookingStatus, PaymentMode, PaymentPreference
from app.models.call import CONNECTED_OUTCOMES, CallDirection, CallLog, CallOutcome
from app.models.integration import InboundEvent, InboundStatus, Integration, IntegrationKind
from app.models.inventory import Building, Floor, Unit, UnitStatus, UnitType
from app.models.lead import (
    BuyingTimeline,
    Configuration,
    Lead,
    LeadActivity,
    LeadCodeCounter,
    LeadSource,
    LeadStatus,
    Purpose,
)
from app.models.marketing import Campaign, Channel, Expense, ExpenseCategory
from app.models.notification import Notification
from app.models.pipeline import DEFAULT_PROBABILITIES, PipelineStage
from app.models.project import Developer, Project, ProjectStatus, ProjectType
from app.models.task import FollowUpTask, TaskStatus, TaskType
from app.models.user import Role, User
from app.models.visit import InterestLevel, SiteVisit, VisitSource, VisitStatus

__all__ = [
    "Booking",
    "BookingEvent",
    "BookingStatus",
    "PaymentMode",
    "PaymentPreference",
    "InboundEvent",
    "InboundStatus",
    "Integration",
    "IntegrationKind",
    "Campaign",
    "Channel",
    "Expense",
    "ExpenseCategory",
    "DEFAULT_PROBABILITIES",
    "PipelineStage",
    "Building",
    "Developer",
    "Floor",
    "ProjectStatus",
    "ProjectType",
    "Unit",
    "UnitStatus",
    "UnitType",
    "CONNECTED_OUTCOMES",
    "CallDirection",
    "CallLog",
    "CallOutcome",
    "InterestLevel",
    "SiteVisit",
    "VisitSource",
    "VisitStatus",
    "AuditLog",
    "Base",
    "BuyingTimeline",
    "Configuration",
    "FollowUpTask",
    "Lead",
    "LeadActivity",
    "LeadCodeCounter",
    "LeadSource",
    "LeadStatus",
    "Notification",
    "Project",
    "Purpose",
    "Role",
    "TaskStatus",
    "TaskType",
    "User",
]
