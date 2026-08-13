"""create space intelligence

Revision ID: 010
Revises: 009
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "010"
down_revision: str = "009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE space_intelligence (
            id UUID PRIMARY KEY,
            knowledge_space_id UUID NOT NULL
                REFERENCES knowledge_spaces(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'processing'
                CONSTRAINT ck_space_intelligence_status_valid
                CHECK (status IN ('processing', 'ready', 'failed')),
            input_signature VARCHAR(64) NOT NULL
                CONSTRAINT ck_space_intelligence_signature_valid
                CHECK (input_signature ~ '^[0-9a-f]{64}$'),
            summary TEXT NOT NULL DEFAULT '',
            key_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
            contradictions JSONB NOT NULL DEFAULT '[]'::jsonb,
            dates JSONB NOT NULL DEFAULT '[]'::jsonb,
            open_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
            provider VARCHAR(50) NOT NULL,
            model VARCHAR(200) NOT NULL DEFAULT '',
            error_message TEXT,
            processing_started_at TIMESTAMPTZ,
            processing_attempt_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_space_intelligence_knowledge_space_id
                UNIQUE (knowledge_space_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_space_intelligence_knowledge_space_id "
        "ON space_intelligence (knowledge_space_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_space_intelligence_knowledge_space_id")
    op.execute("DROP TABLE IF EXISTS space_intelligence")
