"""为图文选题保存所引用的爆款笔记。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_000025"
down_revision: str | None = "20260717_000024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "topics",
        sa.Column("reference_note", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("topics", "reference_note")
