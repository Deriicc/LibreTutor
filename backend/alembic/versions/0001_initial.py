"""initial schema (single-user, no auth)

Revision ID: 0001
Revises:
Create Date: 2026-05-31

Baseline for the open-source single-user build. The schema is created
directly from the SQLAlchemy models (`Base.metadata`), which already
encode the net result of the original migration chain. The only things
not expressible in the model metadata are added explicitly here:
  - the pgvector extension (needed before the Vector column is created),
  - the two performance indexes from the old 0019 migration.
"""
from typing import Sequence, Union

from alembic import op

from app.db import Base
from app import models  # noqa: F401  # register all tables on Base.metadata

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # pgvector type must exist before document_chunks.embedding is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)

    # Perf indexes that can't be expressed in the model metadata.
    # Chat history sorts by (kp_id, created_at).
    op.create_index("ix_messages_kp_created", "messages", ["kp_id", "created_at"])
    # HNSW makes cosine vector search O(log n) instead of a full scan.
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding")
    op.execute("DROP INDEX IF EXISTS ix_messages_kp_created")
    Base.metadata.drop_all(bind=bind)
