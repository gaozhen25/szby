import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.db.models import (
    AccountRecord,
    OwnContentMetricSnapshotRecord,
    OwnDashboardSyncStateRecord,
    OwnSocialContentRecord,
)
from app.services.own_content_analytics import OwnContentAnalyticsService
from tests.db_test_utils import db_session


def test_refresh_releases_database_transaction_during_external_collection(monkeypatch):
    async def collect(service, account, platform_name, code, handle, *, user_id=""):
        assert not service.session.in_transaction()
        assert (platform_name, code, handle, user_id) == (
            "小红书",
            "xhs",
            "red_handle",
            "u_001",
        )
        account.platform_account_identities = {
            "小红书": {
                "input": handle,
                "profileUrl": "https://www.xiaohongshu.com/user/profile/user-1",
            }
        }
        return [
            {
                "platform_content_id": "note_1",
                "title": "新作品",
                "content_url": "https://www.xiaohongshu.com/explore/note_1",
                "cover_url": "",
                "content_type": "normal",
                "published_at": datetime.now(UTC),
                "likes": 10,
                "comments": 2,
                "favorites": 3,
                "shares": 1,
            }
        ]

    monkeypatch.setattr(OwnContentAnalyticsService, "_collect_mediaspider", collect)

    with db_session() as session:
        account = session.get(AccountRecord, "acc1")
        account.platforms = ["小红书"]
        account.platform_accounts = {"小红书": "red_handle"}
        session.commit()

        service = OwnContentAnalyticsService(
            session,
            runtime_settings=SimpleNamespace(
                social_retrieval_provider="mediaspider",
                OWN_DASHBOARD_REFRESH_SECONDS=3600,
            ),
        )
        count = asyncio.run(
            service.refresh(
                user_id="u_001",
                account_id="acc1",
                platform_name="小红书",
            )
        )

        session.expire_all()
        account = session.get(AccountRecord, "acc1")
        state = session.query(OwnDashboardSyncStateRecord).filter_by(
            account_id="acc1", platform="小红书"
        ).one()
        assert count == 1
        assert account.platform_account_identities["小红书"]["input"] == "red_handle"
        assert state.last_success_at is not None
        assert state.last_error_message == ""
        assert session.query(OwnSocialContentRecord).filter_by(
            account_id="acc1", platform="xhs", platform_content_id="note_1"
        ).one().title == "新作品"


def test_refresh_rolls_back_before_recording_persistence_failure(monkeypatch):
    async def collect(
        service, account, platform_name, code, handle, *, user_id=""
    ):  # noqa: ARG001
        return [{"platform_content_id": "note_1"}]

    def fail_persist(service, *args, **kwargs):  # noqa: ARG001
        raise RuntimeError("写库失败")

    monkeypatch.setattr(OwnContentAnalyticsService, "_collect_mediaspider", collect)
    monkeypatch.setattr(OwnContentAnalyticsService, "_persist", fail_persist)

    with db_session() as session:
        account = session.get(AccountRecord, "acc1")
        account.platforms = ["小红书"]
        account.platform_accounts = {"小红书": "red_handle"}
        session.commit()
        rollback_calls = 0
        original_rollback = session.rollback

        def tracked_rollback():
            nonlocal rollback_calls
            rollback_calls += 1
            original_rollback()

        monkeypatch.setattr(session, "rollback", tracked_rollback)
        service = OwnContentAnalyticsService(
            session,
            runtime_settings=SimpleNamespace(
                social_retrieval_provider="mediaspider",
                OWN_DASHBOARD_REFRESH_SECONDS=3600,
            ),
        )

        try:
            asyncio.run(
                service.refresh(
                    user_id="u_001",
                    account_id="acc1",
                    platform_name="小红书",
                )
            )
        except RuntimeError as exc:
            assert str(exc) == "写库失败"
        else:
            raise AssertionError("refresh should fail")

        session.expire_all()
        state = session.query(OwnDashboardSyncStateRecord).filter_by(
            account_id="acc1", platform="小红书"
        ).one()
        assert rollback_calls == 1
        assert state.consecutive_failures == 1
        assert state.last_error_code == "RuntimeError"
        assert state.last_error_message == "写库失败"


def test_hourly_snapshots_build_current_values_and_real_deltas():
    now = datetime.now(UTC).replace(minute=20, second=0, microsecond=0)
    with db_session() as session:
        account = session.get(AccountRecord, "acc1")
        account.platforms = ["抖音"]
        account.platform_accounts = {"抖音": "own_handle"}
        content = OwnSocialContentRecord(
            account_id="acc1",
            platform="dy",
            platform_content_id="video_1",
            title="近期作品",
            content_type="video",
            published_at=now - timedelta(days=1),
            first_seen_at=now - timedelta(days=1),
            last_seen_at=now,
        )
        session.add(content)
        session.flush()
        session.add_all(
            [
                OwnContentMetricSnapshotRecord(
                    content_id=content.id,
                    captured_hour=now - timedelta(hours=25, minutes=20),
                    captured_at=now - timedelta(hours=25),
                    provider="mediaspider",
                    likes=100,
                    comments=10,
                    favorites=20,
                    shares=5,
                ),
                OwnContentMetricSnapshotRecord(
                    content_id=content.id,
                    captured_hour=now - timedelta(hours=1, minutes=20),
                    captured_at=now - timedelta(hours=1),
                    provider="mediaspider",
                    likes=115,
                    comments=12,
                    favorites=24,
                    shares=6,
                ),
                OwnContentMetricSnapshotRecord(
                    content_id=content.id,
                    captured_hour=now.replace(minute=0),
                    captured_at=now,
                    provider="mediaspider",
                    likes=120,
                    comments=13,
                    favorites=27,
                    shares=8,
                ),
                OwnDashboardSyncStateRecord(
                    account_id="acc1",
                    platform="抖音",
                    provider="mediaspider",
                    last_success_at=now,
                    next_refresh_at=now + timedelta(hours=1),
                ),
            ]
        )
        session.commit()

        dashboard = OwnContentAnalyticsService(session).build(
            user_id="u_001",
            account_id="acc1",
            platform_name="抖音",
            days=30,
        )
        item = dashboard.topContents[0]
        metrics = {metric.key: metric.value for metric in dashboard.metrics}

        assert dashboard.provider == "mediaspider"
        assert item.likes == 120
        assert item.comments == 13
        assert item.favorites == 27
        assert item.shares == 8
        assert item.delta1h == 11
        assert item.delta24h == 33
        assert metrics["likes"] == 20
        assert metrics["comments"] == 3
        assert metrics["favorites"] == 7
        assert metrics["shares"] == 3

        trend = OwnContentAnalyticsService(session).trend(
            user_id="u_001",
            account_id="acc1",
            content_id=content.id,
            days=7,
        )
        assert [point.likes for point in trend.points] == [100, 115, 120]


def test_first_snapshot_keeps_changes_unavailable_instead_of_zero():
    now = datetime.now(UTC)
    with db_session() as session:
        account = session.get(AccountRecord, "acc1")
        account.platforms = ["小红书"]
        account.platform_accounts = {"小红书": "red_handle"}
        content = OwnSocialContentRecord(
            account_id="acc1",
            platform="xhs",
            platform_content_id="note_1",
            title="首个快照",
            content_type="normal",
            published_at=now,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(content)
        session.flush()
        session.add(
            OwnContentMetricSnapshotRecord(
                content_id=content.id,
                captured_hour=now.replace(minute=0, second=0, microsecond=0),
                captured_at=now,
                provider="mediaspider",
                likes=10,
                comments=2,
                favorites=3,
                shares=None,
            )
        )
        session.commit()

        dashboard = OwnContentAnalyticsService(session).build(
            user_id="u_001",
            account_id="acc1",
            platform_name="小红书",
            days=7,
        )

        assert dashboard.topContents[0].delta1h is None
        assert dashboard.topContents[0].delta24h is None
        assert {item.key: item.value for item in dashboard.metrics}["likes"] is None
