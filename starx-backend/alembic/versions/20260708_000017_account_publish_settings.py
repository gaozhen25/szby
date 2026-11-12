"""account publish settings

Revision ID: 20260708_000017
Revises: 20260706_000016
Create Date: 2026-07-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260708_000017"
down_revision: str | None = "20260706_000016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("publish_settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.alter_column("accounts", "publish_settings", server_default=None)


def downgrade() -> None:
    op.drop_column("accounts", "publish_settings")
