"""将竞品监控刷新时间统一到北京时间每日凌晨四点。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_000033"
down_revision: str | None = "20260728_000032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEXT_BEIJING_4AM_SQL = """
(
    (
        date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')
        + interval '4 hours'
        + CASE
            WHEN CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai'
                >= date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')
                    + interval '4 hours'
            THEN interval '1 day'
            ELSE interval '0 day'
          END
    ) AT TIME ZONE 'Asia/Shanghai'
)
"""


def upgrade() -> None:
    for table in ("competitor_accounts", "competitor_videos"):
        op.execute(
            f"""
            UPDATE {table}
            SET next_refresh_at = {_NEXT_BEIJING_4AM_SQL}
            WHERE active_workflow_id IS NULL
            """
        )


def downgrade() -> None:
    # 旧版按“任务完成时间 + 6 小时”计算，无法从统一时间点还原历史值。
    pass
