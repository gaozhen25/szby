"""为竞品账号保存最新视频、增量视频与每次视频集合快照。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_000024"
down_revision: str | None = "20260716_000023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competitor_accounts",
        sa.Column("latest_videos", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "competitor_accounts",
        sa.Column("new_videos", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "competitor_accounts",
        sa.Column(
            "video_snapshot_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "competitor_snapshots",
        sa.Column("items", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("competitor_snapshots", "items")
    op.drop_column("competitor_accounts", "video_snapshot_ready")
    op.drop_column("competitor_accounts", "new_videos")
    op.drop_column("competitor_accounts", "latest_videos")
