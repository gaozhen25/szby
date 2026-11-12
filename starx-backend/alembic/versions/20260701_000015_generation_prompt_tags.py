"""generation prompt tags

Revision ID: 20260701_000015
Revises: 20260701_000014
Create Date: 2026-07-01 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_000015"
down_revision: str | None = "20260701_000014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_prompt_tag_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_generation_prompt_tag_categories_account_id"),
        "generation_prompt_tag_categories",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_prompt_tag_categories_user_id"),
        "generation_prompt_tag_categories",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "generation_prompt_tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["generation_prompt_tag_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_generation_prompt_tags_account_id"), "generation_prompt_tags", ["account_id"], unique=False)
    op.create_index(
        op.f("ix_generation_prompt_tags_category_id"), "generation_prompt_tags", ["category_id"], unique=False
    )
    op.create_index(op.f("ix_generation_prompt_tags_user_id"), "generation_prompt_tags", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_generation_prompt_tags_user_id"), table_name="generation_prompt_tags")
    op.drop_index(op.f("ix_generation_prompt_tags_category_id"), table_name="generation_prompt_tags")
    op.drop_index(op.f("ix_generation_prompt_tags_account_id"), table_name="generation_prompt_tags")
    op.drop_table("generation_prompt_tags")
    op.drop_index(op.f("ix_generation_prompt_tag_categories_user_id"), table_name="generation_prompt_tag_categories")
    op.drop_index(op.f("ix_generation_prompt_tag_categories_account_id"), table_name="generation_prompt_tag_categories")
    op.drop_table("generation_prompt_tag_categories")
