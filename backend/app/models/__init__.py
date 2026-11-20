"""Import every model here so Alembic autogenerate can see it."""

from app.models.agreement import Agreement, AgreementStatus
from app.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.booking import Booking, BookingEvent, BookingStatus, PaymentMode, PaymentPreference
from app.models.call import CONNECTED_OUTCOMES, CallDirection, CallLog, CallOutcome
from app.models.case_document import Approval, CaseDocument, DocCategory, Verification, Visibility
from app.models.channel_partner import ChannelPartner
from app.models.demand import Demand, DemandStatus, IssueMethod
from app.models.floor_plan import FloorPlan
from app.models.followup import FollowUpChannel, FollowUpOutcome, PaymentFollowUp
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
from app.models.ledger import (
    ChargeHead,
    Ledger,
    LedgerCharge,
    LedgerStatus,
    ScheduleItem,
    TriggerType,
)
from app.models.loan import (
    Disbursement,
    DisbursementStatus,
    Loan,
    LoanDocRequest,
    VerificationState,
)
from app.models.marketing import Campaign, Channel, Expense, ExpenseCategory
from app.models.milestone import (
    MilestoneEvidence,
    MilestoneProgress,
    MilestoneStatus,
    ProjectMilestone,
)
from app.models.notification import Notification
from app.models.payment import Allocation, FundSource, Receipt, ReceiptMode, ReceiptStatus
from app.models.pipeline import DEFAULT_PROBABILITIES, PipelineStage
from app.models.postsales import (
    CaseEvent,
    CaseStatus,
    CoApplicant,
    CustomerProfile,
    KycDocType,
    KycDocument,
    KycStatus,
    OnboardingStatus,
    OwnershipType,
    PostSalesCase,
)
from app.models.project import Developer, Project, ProjectStatus, ProjectType
from app.models.project_legal import ProjectBank, ProjectLegal
from app.models.project_update import (
    ProjectUpdate,
    ProjectUpdateCorrection,
    ProjectUpdatePhoto,
    UpdateStatus,
)
from app.models.task import FollowUpTask, TaskStatus, TaskType
from app.models.user import Role, User
from app.models.visit import InterestLevel, SiteVisit, VisitSource, VisitStatus

__all__ = [
    "MilestoneProgress",
    "ProjectUpdate",
    "ProjectUpdateCorrection",
    "ProjectUpdatePhoto",
    "UpdateStatus",
    "Appointment",
    "AppointmentKind",
    "AppointmentStatus",
    "Disbursement",
    "DisbursementStatus",
    "Loan",
    "LoanDocRequest",
    "VerificationState",
    "Agreement",
    "AgreementStatus",
    "Approval",
    "CaseDocument",
    "DocCategory",
    "Verification",
    "Visibility",
    "FollowUpChannel",
    "FollowUpOutcome",
    "PaymentFollowUp",
    "Demand",
    "DemandStatus",
    "IssueMethod",
    "MilestoneEvidence",
    "MilestoneStatus",
    "ProjectMilestone",
    "Allocation",
    "FundSource",
    "Receipt",
    "ReceiptMode",
    "ReceiptStatus",
    "ChargeHead",
    "Ledger",
    "LedgerCharge",
    "LedgerStatus",
    "ScheduleItem",
    "TriggerType",
    "CaseEvent",
    "CaseStatus",
    "CoApplicant",
    "CustomerProfile",
    "KycDocType",
    "KycDocument",
    "KycStatus",
    "OnboardingStatus",
    "OwnershipType",
    "PostSalesCase",
    "ProjectBank",
    "ProjectLegal",
    "FloorPlan",
    "ChannelPartner",
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
