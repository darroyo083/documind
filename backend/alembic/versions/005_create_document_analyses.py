"""create document analyses

Revision ID: 005
Revises: 004
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005"
down_revision: str = "004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_analyses (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'processing'
                CONSTRAINT ck_document_analyses_status_valid
                CHECK (status IN ('processing', 'ready', 'failed')),
            document_type VARCHAR(40) NOT NULL DEFAULT 'unknown'
                CONSTRAINT ck_document_analyses_document_type_valid
                CHECK (document_type IN (
                    'contract', 'invoice', 'insurance_policy', 'bank_statement',
                    'tax_document', 'employment_document', 'housing_document',
                    'pension_document', 'official_letter', 'receipt', 'report',
                    'other', 'unknown'
                )),
            normalized_title VARCHAR(500) NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            important_dates JSONB NOT NULL DEFAULT '[]'::jsonb,
            key_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
            provider VARCHAR(50) NOT NULL,
            model VARCHAR(200) NOT NULL DEFAULT '',
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_document_analyses_document_id UNIQUE (document_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_document_analyses_document_id ON document_analyses (document_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_analyses_document_id")
    op.execute("DROP TABLE IF EXISTS document_analyses")
