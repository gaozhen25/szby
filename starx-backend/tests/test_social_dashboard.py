import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.db.models import (
    AccountRecord,
    DashboardAccountSnapshotRecord,
    DashboardContentSnapshotRecord,
)
from app.services.social_dashboard.aggregation import build_social_dashboard
from app.services.social_dashboard.identity import resolve_platform_account
from app.services.social_dashboard.service import SocialDashboardService
from app.services.tikhub_service import (
    TikHubAccount,
    TikHubAccountPage,
    TikHubContent,
    TikHubContentPage,
    TikHubPlatform,
)
from tests.db_test_utils import db_session


class IdentityProviderStub:
    def __init__(self):
        self.search_calls = 0
        self.detail_requests = []

    async def search_accounts(self, request):
        self.search_calls += 1
        return TikHubAccountPage(
            platform=request.platform,
            accounts=[
                TikHubAccount(
                    platform=request.platform,
                    accountId="exact_handle",
                    userId="stable_user_id",
                    name="精确账号",
                ),
                TikHubAccount(
                    platform=request.platform,
                    accountId="similar_handle",
                    userId="other_user_id",
                    name="相似账号",
                ),
            ],
        )

    async def get_account(self, request):
        self.detail_requests.append(request)
        return TikHubAccount(
            platform=TikHubPlatform.DOUYIN,
            accountId="exact_handle",
            userId=request.userId or "stable_user_id",
            name="精确账号",
        )


class DashboardRefreshProviderStub:
    def __init__(self):
        self.detail_calls = 0
        self.content_calls = 0
        self.statistics_calls = 0

    async def get_account(self, request):
        self.detail_calls += 1
        return TikHubAccount(
            platform=request.platform,
            accountId=request.accountId,
            userId=request.userId,
            name="强制刷新账号",
            followers=90,
            totalLikes=120,
            contentCount=1,
        )

    async def list_account_contents(self, request):
        self.content_calls += 1
        return TikHubContentPage(
            platform=request.platform,
            contents=[
                TikHubContent(
                    platform=request.platform,
                    contentId="video_1",
                    title="强制刷新作品",
                    contentType="video",
                    publishedAt=datetime.now(UTC).isoformat(),
                    readCount=300,
                    likeCount=30,
                    commentCount=4,
                    shareCount=5,
                    collectCount=6,
                )
            ],
        )

    async def get_douyin_content_statistics(self, content_ids):
        self.statistics_calls += 1
        return {content_ids[0]: {"views": 333, "likes": 31, "shares": 7}}


def test_identity_resolution_accepts_only_exact_platform_handle():
    provider = IdentityProviderStub()

    account, identity = asyncio.run(
        resolve_platform_account(
            provider,
            platform_name="抖音",
            platform_account="Exact_Handle",
        )
    )
    unresolved, unresolved_identity = asyncio.run(
        resolve_platform_account(
            provider,
            platform_name="抖音",
            platform_account="精确账号",
        )
    )

    assert account is not None
    assert account.userId == "stable_user_id"
    assert provider.search_calls == 0
    assert provider.detail_requests[0].accountId == "Exact_Handle"
    assert provider.detail_requests[0].userId == ""
    assert identity == {
        "input": "Exact_Handle",
        "accountId": "exact_handle",
        "userId": "stable_user_id",
        "profileUrl": "",
        "displayName": "精确账号",
    }
    assert unresolved is None
    assert unresolved_identity is None


def test_dashboard_reuses_today_snapshot_without_calling_tikhub():
    now = datetime.now(UTC)
    observed_date = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    with db_session() as session:
        record = session.get(AccountRecord, "acc1")
        record.platforms = ["抖音"]
        record.platform_accounts = {"抖音": "335476752"}
        record.platform_account_identities = {
            "抖音": {
                "input": "335476752",
                "accountId": "335476752",
                "userId": "stable_sec_user_id",
                "displayName": "每日快照账号",
            }
        }
        session.add(
            DashboardAccountSnapshotRecord(
                account_id="acc1",
                platform="抖音",
                observed_date=observed_date,
                followers=60,
                content_count=1,
                total_likes=56,
                observed_at=now,
            )
        )
        session.add(
            DashboardContentSnapshotRecord(
                account_id="acc1",
                platform="抖音",
                content_id="video_1",
                observed_date=observed_date,
                title="今日快照作品",
                content_type="video",
                published_at=now.isoformat(),
                views=100,
                likes=10,
                comments=2,
                shares=1,
                favorites=3,
                observed_at=now,
            )
        )
        session.commit()

        dashboard = asyncio.run(
            SocialDashboardService(session, object()).build(  # type: ignore[arg-type]
                user_id="u_001",
                account_id="acc1",
                platform_name="抖音",
                days=30,
            )
        )

        assert dashboard.status == "ready"
        assert dashboard.displayName == "每日快照账号"
        assert dashboard.updatedAt == now.isoformat()
        assert dashboard.topContents[0].contentId == "video_1"
        metrics = {item.key: item.value for item in dashboard.metrics}
        assert "exposure" not in metrics
        assert metrics["likes"] == 10


def test_dashboard_force_refresh_bypasses_today_snapshot_and_updates_metrics():
    now = datetime.now(UTC)
    observed_date = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    provider = DashboardRefreshProviderStub()
    with db_session() as session:
        record = session.get(AccountRecord, "acc1")
        record.platforms = ["抖音"]
        record.platform_accounts = {"抖音": "335476752"}
        record.platform_account_identities = {
            "抖音": {
                "input": "335476752",
                "accountId": "335476752",
                "userId": "stable_sec_user_id",
                "displayName": "每日快照账号",
            }
        }
        session.add(
            DashboardAccountSnapshotRecord(
                account_id="acc1",
                platform="抖音",
                observed_date=observed_date,
                followers=60,
                content_count=1,
                total_likes=56,
                observed_at=now,
            )
        )
        session.add(
            DashboardContentSnapshotRecord(
                account_id="acc1",
                platform="抖音",
                content_id="video_1",
                observed_date=observed_date,
                title="今日快照作品",
                content_type="video",
                published_at=now.isoformat(),
                views=100,
                likes=10,
                comments=2,
                shares=1,
                favorites=3,
                observed_at=now,
            )
        )
        session.commit()

        dashboard = asyncio.run(
            SocialDashboardService(session, provider).build(
                user_id="u_001",
                account_id="acc1",
                platform_name="抖音",
                days=30,
                force_refresh=True,
            )
        )

        metrics = {item.key: item.value for item in dashboard.metrics}
        assert dashboard.status == "ready"
        assert dashboard.displayName == "强制刷新账号"
        assert dashboard.topContents[0].title == "强制刷新作品"
        assert dashboard.topContents[0].likes == 30
        assert "exposure" not in metrics
        assert metrics["likes"] == 30
        assert provider.detail_calls == 1
        assert provider.content_calls == 1
        assert provider.statistics_calls == 0


def test_douyin_dashboard_uses_interaction_metrics_without_play_metrics():
    now = datetime(2026, 7, 23, 12, tzinfo=UTC)
    contents = [
        TikHubContent(
            platform=TikHubPlatform.DOUYIN,
            contentId="video_1",
            title="高表现视频",
            contentType="video",
            publishedAt=(now - timedelta(days=1)).isoformat(),
            readCount=1000,
            likeCount=80,
            commentCount=10,
            shareCount=5,
            collectCount=5,
        ),
        TikHubContent(
            platform=TikHubPlatform.DOUYIN,
            contentId="video_old",
            title="周期外视频",
            contentType="video",
            publishedAt=(now - timedelta(days=40)).isoformat(),
            readCount=9000,
            likeCount=900,
        ),
    ]

    dashboard = build_social_dashboard(
        platform_name="抖音",
        platform_account="douyin_123",
        account=TikHubAccount(
            platform=TikHubPlatform.DOUYIN,
            accountId="douyin_123",
            userId="sec_user",
            name="示例账号",
            followers=1200,
        ),
        contents=contents,
        days=30,
        previous_followers=1100,
        now=now,
    )

    metrics = {item.key: item for item in dashboard.metrics}
    assert not hasattr(dashboard, "metricLabel")
    assert "exposure" not in metrics
    assert metrics["likes"].value == 80
    assert metrics["comments"].value == 10
    assert metrics["shares"].value == 5
    assert metrics["favorites"].value == 5
    assert metrics["followers"].label == "粉丝数"
    assert metrics["followers"].value == 1200
    assert metrics["followers"].change == 100
    assert metrics["followers"].note == "近 30 天净增 +100"
    assert dashboard.contentStructure[0].label == "视频"
    assert dashboard.topContents[0].contentId == "video_1"
    assert dashboard.topContents[0].likes == 80
    assert dashboard.topContents[0].favorites == 5
    assert dashboard.topContents[0].comments == 10
    assert dashboard.topContents[0].shares == 5
    assert dashboard.trend == []


def test_xiaohongshu_dashboard_uses_interactions_without_read_denominator():
    dashboard = build_social_dashboard(
        platform_name="小红书",
        platform_account="red_123",
        account=TikHubAccount(
            platform=TikHubPlatform.XIAOHONGSHU,
            accountId="red_123",
            userId="user_123",
            name="示例账号",
            followers=100,
        ),
        contents=[
            TikHubContent(
                platform=TikHubPlatform.XIAOHONGSHU,
                contentId="note_1",
                title="图文笔记",
                contentType="normal",
                publishedAt="2026-07-22T12:00:00Z",
                likeCount=10,
                commentCount=2,
                collectCount=3,
            )
        ],
        days=30,
        previous_followers=None,
        now=datetime(2026, 7, 23, 12, tzinfo=UTC),
    )

    metrics = {item.key: item for item in dashboard.metrics}
    assert not hasattr(dashboard, "metricLabel")
    assert "exposure" not in metrics
    assert metrics["likes"].value == 10
    assert metrics["comments"].value == 2
    assert metrics["shares"].value == 0
    assert metrics["favorites"].value == 3
    assert metrics["followers"].label == "粉丝数"
    assert metrics["followers"].value == 100
    assert metrics["followers"].change is None
    assert metrics["followers"].available is True
    assert metrics["followers"].note == "已记录当前粉丝数，完成周期快照后展示真实涨粉"
    assert dashboard.contentStructure[0].label == "图文"
