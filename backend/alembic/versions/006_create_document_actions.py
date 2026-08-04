"""create document action sets and actions

Revision ID: 006
Revises: 005
Create Date: 2026-08-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str = "005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_action_sets (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'processing'
                CONSTRAINT ck_document_action_sets_status_valid
                CHECK (status IN ('processing', 'ready', 'failed')),
            provider VARCHAR(50) NOT NULL,
            model VARCHAR(200) NOT NULL DEFAULT '',
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_document_action_sets_document_id UNIQUE (document_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_document_action_sets_document_id ON document_action_sets (document_id)"
    )
    op.execute(
        """
        CREATE TABLE document_actions (
            id UUID PRIMARY KEY,
            action_set_id UUID NOT NULL
                REFERENCES document_action_sets(id) ON DELETE CASCADE,
            position INTEGER NOT NULL
                CONSTRAINT ck_document_actions_position_nonnegative CHECK (position >= 0),
            action_type VARCHAR(40) NOT NULL
                CONSTRAINT ck_document_actions_action_type_valid
                CHECK (action_type IN (
                    'required_action', 'deadline', 'reminder', 'recommended_action'
                )),
            title VARCHAR(500) NOT NULL,
            description TEXT,
            timing_text VARCHAR(500),
            due_date DATE,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CONSTRAINT ck_document_actions_status_valid
                CHECK (status IN ('pending', 'completed')),
            sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_document_actions_position UNIQUE (action_set_id, position)
        )
        """
    )
    op.execute("CREATE INDEX ix_document_actions_action_set_id ON document_actions (action_set_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_actions_action_set_id")
    op.execute("DROP TABLE IF EXISTS document_actions")
    op.execute("DROP INDEX IF EXISTS ix_document_action_sets_document_id")
    op.execute("DROP TABLE IF EXISTS document_action_sets")
