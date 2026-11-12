from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.db.models import (
    AccountRecord,
    DashboardAccountSnapshotRecord,
    DashboardContentSnapshotRecord,
)
from app.services.account_report.collection.dashboard_source import (
    load_dashboard_crawl_results,
)
from tests.db_test_utils import db_session


def test_dashboard_snapshots_are_reused_as_current_account_crawl_results():
    now = datetime.now(UTC)
    observed_date = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    with db_session() as session:
        account = session.get(AccountRecord, "acc1")
        account.platforms = ["小红书"]
        account.platform_accounts = {"小红书": "owner-handle"}
        account.platform_account_identities = {
            "小红书": {
                "accountId": "owner-handle",
                "userId": "stable-owner-id",
                "displayName": "自己的账号",
                "profileUrl": "https://www.xiaohongshu.com/user/profile/stable-owner-id",
            }
        }
        session.add(
            DashboardAccountSnapshotRecord(
                account_id="acc1",
                platform="小红书",
                observed_date=observed_date,
                followers=1200,
                follows=88,
                content_count=20,
                total_likes=5000,
                observed_at=now,
            )
        )
        session.add(
            DashboardContentSnapshotRecord(
                account_id="acc1",
                platform="小红书",
                content_id="own-note-1",
                observed_date=observed_date,
                title="自己的主页作品",
                content_url="https://www.xiaohongshu.com/explore/own-note-1",
                cover_url="https://example.test/cover.jpg",
                content_type="image",
                published_at=now.isoformat(),
                views=3000,
                likes=300,
                comments=20,
                shares=10,
                favorites=80,
                observed_at=now,
            )
        )
        session.commit()

        results = load_dashboard_crawl_results(
            session,
            account_id="acc1",
            platform_names=["小红书"],
            observed_date=observed_date,
        )

    assert len(results) == 1
    result = results[0]
    assert result.platform == "xhs"
    assert result.crawl_type == "creator"
    assert result.source_operations == ["dashboard_account_snapshot"]
    assert result.creators[0] == {
        "user_id": "stable-owner-id",
        "nickname": "自己的账号",
        "display_name": "自己的账号",
        "profile_url": "https://www.xiaohongshu.com/user/profile/stable-owner-id",
        "fans_count": 1200,
        "follows_count": 88,
        "works_count": 20,
        "liked_count": 5000,
        "source_operation": "dashboard_account_snapshot",
        "evidence_completeness": 1.0,
    }
    assert result.contents[0]["note_id"] == "own-note-1"
    assert result.contents[0]["user_id"] == "stable-owner-id"
    assert result.contents[0]["view_count"] == 3000
    assert result.contents[0]["collected_count"] == 80
