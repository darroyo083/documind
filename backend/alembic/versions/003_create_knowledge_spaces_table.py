"""create knowledge_spaces table

Revision ID: 003
Revises: 002
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str = "002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge_spaces (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX ix_knowledge_spaces_user_id ON knowledge_spaces (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_spaces_user_id")
    op.execute("DROP TABLE IF EXISTS knowledge_spaces")
