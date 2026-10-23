"""Import every model here so Alembic autogenerate can see it."""

from app.models.audit import AuditLog
from app.models.base import Base
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
from app.models.notification import Notification
from app.models.project import Project
from app.models.task import FollowUpTask, TaskStatus, TaskType
from app.models.user import Role, User

__all__ = [
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
