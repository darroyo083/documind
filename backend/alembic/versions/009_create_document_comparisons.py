"""create document comparisons

Revision ID: 009
Revises: 008
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str = "008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_comparisons (
            id UUID PRIMARY KEY,
            knowledge_space_id UUID NOT NULL
                REFERENCES knowledge_spaces(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'processing'
                CONSTRAINT ck_document_comparisons_status_valid
                CHECK (status IN ('processing', 'ready', 'failed')),
            comparison_signature VARCHAR(64) NOT NULL
                CONSTRAINT ck_document_comparisons_signature_valid
                CHECK (comparison_signature ~ '^[0-9a-f]{64}$'),
            focus TEXT,
            title VARCHAR(200) NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            comparison_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
            key_differences JSONB NOT NULL DEFAULT '[]'::jsonb,
            commonalities JSONB NOT NULL DEFAULT '[]'::jsonb,
            provider VARCHAR(50) NOT NULL,
            model VARCHAR(200) NOT NULL DEFAULT '',
            error_message TEXT,
            processing_started_at TIMESTAMPTZ,
            processing_attempt_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_document_comparisons_signature
                UNIQUE (knowledge_space_id, comparison_signature)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_comparison_documents (
            id UUID PRIMARY KEY,
            comparison_id UUID NOT NULL
                REFERENCES document_comparisons(id) ON DELETE CASCADE,
            document_id UUID NOT NULL
                REFERENCES documents(id) ON DELETE CASCADE,
            position INTEGER NOT NULL
                CONSTRAINT ck_document_comparison_documents_position
                CHECK (position >= 0),
            CONSTRAINT uq_document_comparison_documents_member
                UNIQUE (comparison_id, document_id),
            CONSTRAINT uq_document_comparison_documents_position
                UNIQUE (comparison_id, position)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_document_comparisons_knowledge_space_id "
        "ON document_comparisons (knowledge_space_id)"
    )
    op.execute(
        "CREATE INDEX ix_document_comparison_documents_comparison_id "
        "ON document_comparison_documents (comparison_id)"
    )
    op.execute(
        "CREATE INDEX ix_document_comparison_documents_document_id "
        "ON document_comparison_documents (document_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_comparison_documents_document_id")
    op.execute("DROP INDEX IF EXISTS ix_document_comparison_documents_comparison_id")
    op.execute("DROP INDEX IF EXISTS ix_document_comparisons_knowledge_space_id")
    op.execute("DROP TABLE IF EXISTS document_comparison_documents")
    op.execute("DROP TABLE IF EXISTS document_comparisons")
