"""create reference documents and chunks

Revision ID: 007
Revises: 006
Create Date: 2026-08-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str = "006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE reference_documents (
            id UUID PRIMARY KEY,
            title VARCHAR(500) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'ready'
                CONSTRAINT ck_reference_documents_status_valid
                CHECK (status IN ('ready', 'failed')),
            content_sha256 VARCHAR(64) NOT NULL UNIQUE,
            page_count INTEGER
                CONSTRAINT ck_reference_documents_page_count_positive
                CHECK (page_count IS NULL OR page_count > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE reference_document_chunks (
            id UUID PRIMARY KEY,
            reference_document_id UUID NOT NULL
                REFERENCES reference_documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL
                CONSTRAINT ck_reference_document_chunks_page_number_positive
                CHECK (page_number > 0),
            chunk_index INTEGER NOT NULL
                CONSTRAINT ck_reference_document_chunks_index_nonnegative
                CHECK (chunk_index >= 0),
            content TEXT NOT NULL
                CONSTRAINT ck_reference_document_chunks_content_nonempty
                CHECK (length(content) > 0),
            embedding VECTOR(384) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_reference_document_chunks_position
                UNIQUE (reference_document_id, chunk_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_reference_document_chunks_reference_document_id "
        "ON reference_document_chunks (reference_document_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_reference_document_chunks_reference_document_id")
    op.execute("DROP TABLE IF EXISTS reference_document_chunks")
    op.execute("DROP TABLE IF EXISTS reference_documents")
