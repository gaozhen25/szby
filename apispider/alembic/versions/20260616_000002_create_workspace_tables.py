"""create workspace tables

Revision ID: 20260616_000002
Revises: 20260615_000001
Create Date: 2026-06-16 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260616_000002"
down_revision = "20260615_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_topics_account_id", "topics", ["account_id"], unique=False)

    op.create_table(
        "dashboards",
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), primary_key=True),
        sa.Column("views", sa.String(length=32), nullable=False),
        sa.Column("change_count", sa.Integer(), nullable=False),
        sa.Column("creation", sa.Integer(), nullable=False),
        sa.Column("tools", sa.Integer(), nullable=False),
        sa.Column("competitor_count", sa.Integer(), nullable=False),
        sa.Column("competitor_posts", sa.Integer(), nullable=False),
        sa.Column("material_count", sa.Integer(), nullable=False),
    )

    op.create_table(
        "reports",
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), primary_key=True),
        sa.Column("competitors", sa.Text(), nullable=False),
        sa.Column("prohibited_words", sa.Text(), nullable=False),
        sa.Column("target_users", sa.Text(), nullable=False),
        sa.Column("hot_content", sa.Text(), nullable=False),
        sa.Column("top_bloggers", sa.Text(), nullable=False),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("updated", sa.String(length=32), nullable=False),
        sa.Column("target_platform", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_tasks_account_id", "tasks", ["account_id"], unique=False)

    op.create_table(
        "materials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("material_type", sa.String(length=32), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("material_date", sa.String(length=32), nullable=False),
        sa.Column("thumb", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_materials_account_id", "materials", ["account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_materials_account_id", table_name="materials")
    op.drop_table("materials")
    op.drop_index("ix_tasks_account_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("reports")
    op.drop_table("dashboards")
    op.drop_index("ix_topics_account_id", table_name="topics")
    op.drop_table("topics")
