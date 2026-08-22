"""add document content hash and processing timestamps

Revision ID: 013
Revises: 012
Create Date: 2026-08-22

``content_sha256`` enables per-Space duplicate-upload rejection; legacy rows
keep NULL (meaning "hash unknown") via a partial unique index, so no backfill
is required and existing data never violates the constraint.
``processing_started_at`` powers compare-and-set recovery of documents left in
PROCESSING by a crash: a retry can atomically reclaim a stale claim.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "013"
down_revision: str = "012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN content_sha256 VARCHAR(64)")
    op.execute("ALTER TABLE documents ADD COLUMN processing_started_at TIMESTAMPTZ")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_documents_space_content_hash
        ON documents (knowledge_space_id, content_sha256)
        WHERE content_sha256 IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_documents_space_content_hash")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS processing_started_at")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS content_sha256")
