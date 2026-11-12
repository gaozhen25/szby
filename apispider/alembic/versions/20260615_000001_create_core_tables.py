"""create core tables

Revision ID: 20260615_000001
Revises:
Create Date: 2026-06-15 14:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260615_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("avatar", sa.String(length=8), nullable=False),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_accounts_user_id", "accounts", ["user_id"], unique=False)

    op.create_table(
        "account_quotas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("quota_date", sa.Date(), nullable=False),
        sa.Column("change_batch_limit", sa.Integer(), nullable=False),
        sa.Column("change_batch_used", sa.Integer(), nullable=False),
        sa.Column("change_single_limit", sa.Integer(), nullable=False),
        sa.Column("change_single_used", sa.Integer(), nullable=False),
        sa.Column("ai_image_limit", sa.Integer(), nullable=False),
        sa.Column("ai_image_used", sa.Integer(), nullable=False),
    )
    op.create_index("ix_account_quotas_account_id", "account_quotas", ["account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_account_quotas_account_id", table_name="account_quotas")
    op.drop_table("account_quotas")
    op.drop_index("ix_accounts_user_id", table_name="accounts")
    op.drop_table("accounts")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
