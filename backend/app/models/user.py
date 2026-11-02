import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Identity, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Role(enum.StrEnum):
    admin = "admin"  # CRM administrator: configuration and users
    # Pre-sales
    manager = "manager"  # sales manager
    executive = "executive"  # sales executive
    docs = "docs"  # documents staff
    # Post-sales (from the post-sales CRM specification)
    postsales_exec = "postsales_exec"  # customer coordination, KYC, document follow-up
    crm_manager = "crm_manager"  # work allocation, escalations, supervision
    finance = "finance"  # receipts, ledger reconciliation
    finance_approver = "finance_approver"  # financial approvals and adjustments (checker)
    legal = "legal"  # agreements, legal review, registration
    project_manager = "project_manager"  # milestones, construction evidence, readiness
    site = "site"  # inspection, snagging, handover
    service = "service"  # customer service desk
    after_sales = "after_sales"  # defects, warranties
    management = "management"  # dashboards and reports
    auditor = "auditor"  # read-only audit access


SALES_ROLES = (Role.admin, Role.manager, Role.executive)
LEAD_READERS = (Role.admin, Role.manager, Role.executive, Role.docs)
POSTSALES_ROLES = (
    Role.admin,
    Role.crm_manager,
    Role.postsales_exec,
    Role.finance,
    Role.finance_approver,
    Role.legal,
    Role.project_manager,
    Role.site,
    Role.service,
    Role.after_sales,
    Role.management,
    Role.auditor,
)
# Who may change post-sales cases, customer details and KYC
CASE_EDITORS = (Role.admin, Role.crm_manager, Role.postsales_exec)
# Who may open KYC files (sensitive identity documents)
KYC_VIEWERS = (Role.admin, Role.crm_manager, Role.postsales_exec, Role.legal, Role.auditor)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Incremented on password change / deactivation; invalidates every issued token.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
