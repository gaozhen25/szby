from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.services.competitor_monitoring.schedule import next_daily_refresh_at


def test_before_beijing_4am_returns_same_day_4am():
    now = datetime(2026, 7, 30, 19, 59, tzinfo=UTC)  # 北京时间 03:59

    assert next_daily_refresh_at(
        now, hour=4, timezone_name="Asia/Shanghai"
    ) == datetime(2026, 7, 30, 20, 0, tzinfo=UTC)


def test_at_beijing_4am_returns_next_day_4am():
    now = datetime(2026, 7, 30, 20, 0, tzinfo=UTC)  # 北京时间 04:00

    assert next_daily_refresh_at(
        now, hour=4, timezone_name="Asia/Shanghai"
    ) == datetime(2026, 7, 31, 20, 0, tzinfo=UTC)


def test_after_beijing_4am_returns_next_day_4am():
    now = datetime(2026, 7, 31, 2, 0, tzinfo=UTC)  # 北京时间 10:00

    assert next_daily_refresh_at(
        now, hour=4, timezone_name="Asia/Shanghai"
    ) == datetime(2026, 7, 31, 20, 0, tzinfo=UTC)


def test_naive_datetime_is_treated_as_utc():
    now = datetime(2026, 7, 30, 19, 59)

    result = next_daily_refresh_at(now, hour=4, timezone_name="Asia/Shanghai")

    assert result.astimezone(ZoneInfo("Asia/Shanghai")).isoformat() == (
        "2026-07-31T04:00:00+08:00"
    )
