"""account platforms json

Revision ID: 20260616_000004
Revises: 20260616_000003
Create Date: 2026-06-16 20:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260616_000004"
down_revision = "20260616_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("platforms", sa.JSON(), nullable=True))
    op.execute("UPDATE accounts SET platforms = json_build_array(platform)")
    op.alter_column("accounts", "platforms", nullable=False)


def downgrade() -> None:
    op.drop_column("accounts", "platforms")
