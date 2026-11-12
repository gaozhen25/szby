"""extract asset persistence

Revision ID: 20260714_000018
Revises: 20260708_000017
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_000018"
down_revision: str | None = "20260708_000017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extract_histories",
        sa.Column("persistence_status", sa.String(length=16), nullable=False, server_default="external"),
    )
    op.add_column("extract_histories", sa.Column("persistence_job_id", sa.String(length=36), nullable=True))
    op.add_column(
        "extract_histories",
        sa.Column("persistence_error", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("extract_histories", sa.Column("persisted_at", sa.DateTime(), nullable=True))
    op.add_column(
        "extract_histories",
        sa.Column("media_url_map", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index(
        "ix_extract_histories_persistence_job_id",
        "extract_histories",
        ["persistence_job_id"],
        unique=False,
    )
    op.add_column(
        "materials",
        sa.Column("assets", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.alter_column("extract_histories", "persistence_status", server_default=None)
    op.alter_column("extract_histories", "persistence_error", server_default=None)
    op.alter_column("extract_histories", "media_url_map", server_default=None)
    op.alter_column("materials", "assets", server_default=None)


def downgrade() -> None:
    op.drop_column("materials", "assets")
    op.drop_index("ix_extract_histories_persistence_job_id", table_name="extract_histories")
    op.drop_column("extract_histories", "media_url_map")
    op.drop_column("extract_histories", "persisted_at")
    op.drop_column("extract_histories", "persistence_error")
    op.drop_column("extract_histories", "persistence_job_id")
    op.drop_column("extract_histories", "persistence_status")
