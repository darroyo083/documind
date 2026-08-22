"""add chunk full-text search vectors

Revision ID: 012
Revises: 011
Create Date: 2026-08-22

Adds a stored ``tsvector`` generated column plus a GIN index to both chunk
tables so hybrid retrieval can combine semantic similarity with lexical
relevance. Generated columns keep the search index transactionally consistent
with ``content`` without application-side triggers.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "012"
down_revision: str = "011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_chunks ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_search_vector "
        "ON document_chunks USING GIN (search_vector)"
    )
    op.execute(
        """
        ALTER TABLE reference_document_chunks ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_reference_document_chunks_search_vector "
        "ON reference_document_chunks USING GIN (search_vector)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_reference_document_chunks_search_vector")
    op.execute("ALTER TABLE reference_document_chunks DROP COLUMN IF EXISTS search_vector")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_search_vector")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS search_vector")
