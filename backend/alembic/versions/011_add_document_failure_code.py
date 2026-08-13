"""add document failure code

Revision ID: 011
Revises: 010
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str = "010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents ADD COLUMN failure_code VARCHAR(40)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS failure_code")
