"""竞品监控的每日刷新时间计算。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def next_daily_refresh_at(
    now: datetime,
    *,
    hour: int,
    timezone_name: str,
) -> datetime:
    """返回指定时区下一次整点刷新时间，并统一转换为 UTC。"""

    utc_now = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    timezone = ZoneInfo(timezone_name)
    local_now = utc_now.astimezone(timezone)
    candidate = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)
