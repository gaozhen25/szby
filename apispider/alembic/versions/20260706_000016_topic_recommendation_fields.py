"""topic recommendation fields

Revision ID: 20260706_000016
Revises: 20260701_000015
Create Date: 2026-07-06 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260706_000016"
down_revision: str | None = "20260701_000015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("topics", sa.Column("reason", sa.Text(), nullable=False, server_default=""))
    op.add_column("topics", sa.Column("platforms", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("topics", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("topics", sa.Column("batch_id", sa.String(length=36), nullable=False, server_default=""))
    op.add_column("topics", sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.add_column("topics", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.alter_column("topics", "reason", server_default=None)
    op.alter_column("topics", "platforms", server_default=None)
    op.alter_column("topics", "sort_order", server_default=None)
    op.alter_column("topics", "batch_id", server_default=None)
    op.alter_column("topics", "created_at", server_default=None)
    op.alter_column("topics", "updated_at", server_default=None)


def downgrade() -> None:
    op.drop_column("topics", "updated_at")
    op.drop_column("topics", "created_at")
    op.drop_column("topics", "batch_id")
    op.drop_column("topics", "sort_order")
    op.drop_column("topics", "platforms")
    op.drop_column("topics", "reason")
