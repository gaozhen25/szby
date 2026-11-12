"""为账号报告增加人工相似账号配置。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_000027"
down_revision: str | None = "20260719_000026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column(
            "manual_similar_accounts",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "reports",
        sa.Column(
            "excluded_similar_account_keys",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("reports", "excluded_similar_account_keys")
    op.drop_column("reports", "manual_similar_accounts")
