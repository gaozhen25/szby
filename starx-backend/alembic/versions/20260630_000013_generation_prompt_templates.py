"""generation prompt templates

Revision ID: 20260630_000013
Revises: 20260630_000012
Create Date: 2026-06-30 21:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260630_000013"
down_revision: str | None = "20260630_000012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_prompt_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("selected_tag_ids", sa.JSON(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("preview_prompt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_generation_prompt_templates_account_id"),
        "generation_prompt_templates",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_prompt_templates_user_id"),
        "generation_prompt_templates",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_generation_prompt_templates_user_id"), table_name="generation_prompt_templates")
    op.drop_index(op.f("ix_generation_prompt_templates_account_id"), table_name="generation_prompt_templates")
    op.drop_table("generation_prompt_templates")
