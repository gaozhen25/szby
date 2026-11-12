"""add account platform

Revision ID: 20260616_000003
Revises: 20260616_000002
Create Date: 2026-06-16 19:40:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260616_000003"
down_revision = "20260616_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="小红书"),
    )
    op.execute("UPDATE accounts SET platform = '小红书' WHERE id = 'acc1'")
    op.execute("UPDATE accounts SET platform = '抖音' WHERE id = 'acc2'")
    op.execute("UPDATE accounts SET platform = '视频号' WHERE id = 'acc3'")
    op.alter_column("accounts", "platform", server_default=None)


def downgrade() -> None:
    op.drop_column("accounts", "platform")
