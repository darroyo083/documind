"""create documents and chunks

Revision ID: 004
Revises: 003
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str = "003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE documents (
            id UUID PRIMARY KEY,
            knowledge_space_id UUID NOT NULL REFERENCES knowledge_spaces(id) ON DELETE CASCADE,
            original_filename VARCHAR(255) NOT NULL,
            storage_key VARCHAR(255) NOT NULL UNIQUE,
            media_type VARCHAR(100) NOT NULL,
            file_size BIGINT NOT NULL
                CONSTRAINT ck_documents_file_size_positive CHECK (file_size > 0),
            page_count INTEGER
                CONSTRAINT ck_documents_page_count_positive
                CHECK (page_count IS NULL OR page_count > 0),
            status VARCHAR(20) NOT NULL DEFAULT 'processing'
                CONSTRAINT ck_documents_status_valid
                CHECK (status IN ('processing', 'ready', 'failed')),
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX ix_documents_knowledge_space_id ON documents (knowledge_space_id)")
    op.execute(
        """
        CREATE TABLE document_chunks (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL
                CONSTRAINT ck_document_chunks_page_number_positive CHECK (page_number > 0),
            chunk_index INTEGER NOT NULL
                CONSTRAINT ck_document_chunks_index_nonnegative CHECK (chunk_index >= 0),
            content TEXT NOT NULL
                CONSTRAINT ck_document_chunks_content_nonempty CHECK (length(content) > 0),
            character_count INTEGER NOT NULL
                CONSTRAINT ck_document_chunks_character_count_positive
                CHECK (character_count > 0),
            embedding VECTOR(384) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_document_chunks_position UNIQUE (document_id, chunk_index)
        )
        """
    )
    op.execute("CREATE INDEX ix_document_chunks_document_id ON document_chunks (document_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_document_id")
    op.execute("DROP TABLE IF EXISTS document_chunks")
    op.execute("DROP INDEX IF EXISTS ix_documents_knowledge_space_id")
    op.execute("DROP TABLE IF EXISTS documents")
