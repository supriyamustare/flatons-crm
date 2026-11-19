"""notification links open the right tab

Revision ID: 56fd8e2d320f
Revises: 2e2924c90d99
Create Date: 2026-11-19 07:54:32.325217

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "56fd8e2d320f"
down_revision: str | Sequence[str] | None = "2e2924c90d99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Existing notifications open the right tab of the case, like new ones."""
    op.execute(
        "UPDATE notifications SET link = link || '?tab=ledger' "
        "WHERE link ~ '^/post-sales/[0-9]+$' AND type IN ('ledger_approval', 'ledger_approved', 'ledger_returned')"
    )
    op.execute(
        "UPDATE notifications SET link = link || '?tab=demands' "
        "WHERE link ~ '^/post-sales/[0-9]+$' AND type IN ('demand_approval', 'demand_due_soon', 'demand_due_today', 'demand_overdue')"
    )
    op.execute(
        "UPDATE notifications SET link = link || '?tab=followups' "
        "WHERE link ~ '^/post-sales/[0-9]+$' AND type IN ('promise_broken', 'payment_follow_up_due')"
    )
    op.execute(
        "UPDATE notifications SET link = link || '?tab=loan' "
        "WHERE link ~ '^/post-sales/[0-9]+$' AND type IN ('loan_disbursement_delayed', 'loan_follow_up_due', 'loan_sanction_expiring')"
    )
    op.execute(
        "UPDATE notifications SET link = link || '?tab=agreement' "
        "WHERE link ~ '^/post-sales/[0-9]+$' AND type IN ('agreement_review')"
    )
    op.execute(
        "UPDATE notifications SET link = link || '?tab=handover' "
        "WHERE link ~ '^/post-sales/[0-9]+$' AND type IN ('handover')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE notifications SET link = split_part(link, '?', 1) WHERE link ~ '^/post-sales/[0-9]+\\?tab='"
    )
