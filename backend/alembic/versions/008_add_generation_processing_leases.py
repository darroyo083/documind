"""add generation processing leases

Revision ID: 008
Revises: 007
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "008"
down_revision: str = "007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_analyses ADD COLUMN processing_started_at TIMESTAMPTZ")
    op.execute("ALTER TABLE document_analyses ADD COLUMN processing_attempt_id UUID")
    op.execute("ALTER TABLE document_action_sets ADD COLUMN processing_started_at TIMESTAMPTZ")
    op.execute("ALTER TABLE document_action_sets ADD COLUMN processing_attempt_id UUID")
    op.execute(
        "UPDATE document_analyses SET processing_started_at = updated_at "
        "WHERE status = 'processing'"
    )
    op.execute(
        "UPDATE document_action_sets SET processing_started_at = updated_at "
        "WHERE status = 'processing'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE document_action_sets DROP COLUMN processing_attempt_id")
    op.execute("ALTER TABLE document_action_sets DROP COLUMN processing_started_at")
    op.execute("ALTER TABLE document_analyses DROP COLUMN processing_attempt_id")
    op.execute("ALTER TABLE document_analyses DROP COLUMN processing_started_at")
