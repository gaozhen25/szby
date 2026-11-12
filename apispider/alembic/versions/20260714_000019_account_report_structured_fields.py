"""为账号报告增加结构化字段

Revision ID: 20260714_000019
Revises: 20260714_000018
Create Date: 2026-07-14 00:00:19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_000019"
down_revision: str | None = "20260714_000018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_columns = {
        "similar_accounts": "[]",
        "compliance_rules": "[]",
        "target_user_profile": "{}",
        "hot_contents": "[]",
        "top_blogger_details": "[]",
        "content_strategy": "{}",
        "source_meta": "{}",
    }
    for column_name, default_json in json_columns.items():
        op.add_column(
            "reports",
            sa.Column(column_name, sa.JSON(), nullable=False, server_default=sa.text(f"'{default_json}'")),
        )
    op.add_column(
        "reports",
        sa.Column("report_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("reports", sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True))

    for column_name in json_columns:
        op.alter_column("reports", column_name, server_default=None)
    op.alter_column("reports", "report_version", server_default=None)


def downgrade() -> None:
    op.drop_column("reports", "generated_at")
    op.drop_column("reports", "report_version")
    op.drop_column("reports", "source_meta")
    op.drop_column("reports", "content_strategy")
    op.drop_column("reports", "top_blogger_details")
    op.drop_column("reports", "hot_contents")
    op.drop_column("reports", "target_user_profile")
    op.drop_column("reports", "compliance_rules")
    op.drop_column("reports", "similar_accounts")
