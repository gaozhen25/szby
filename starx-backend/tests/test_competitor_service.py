import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.init_db import init_database
from app.db.models import (
    CompetitorSnapshotRecord,
    CompetitorVideoRecord,
    WorkflowRecord,
)
from app.services.competitor_monitoring import repository as competitor_repository
from app.services.competitor_monitoring.models import NormalizedCompetitor
from app.services.competitor_monitoring.service import (
    CompetitorMonitoringService,
    CompetitorTargetNotFound,
    DuplicateCompetitorTarget,
)
from app.services.competitor_monitoring.workflow import CompetitorRefreshWorkflow
from app.services.mediaspider.failure_catalog import public_crawler_failure
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerExecutionError,
)


@pytest.fixture
def competitor_service():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return CompetitorMonitoringService(session_factory=factory)


def test_add_and_delete_both_target_types(competitor_service):
    account, account_workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/a"
    )
    video, video_workflow = competitor_service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/1"
    )

    assert account_workflow.input_payload["targetType"] == "account"
    assert account.sec_user_id == "a"
    assert video_workflow.input_payload["targetType"] == "video"
    assert account.active_workflow_id == account_workflow.id
    assert video.active_workflow_id == video_workflow.id
    account_next = account.next_refresh_at.replace(tzinfo=UTC)
    video_next = video.next_refresh_at.replace(tzinfo=UTC)
    assert account_next.astimezone(ZoneInfo("Asia/Shanghai")).time().isoformat() == (
        "04:00:00"
    )
    assert video_next.astimezone(ZoneInfo("Asia/Shanghai")).time().isoformat() == (
        "04:00:00"
    )

    competitor_service.delete_account("u_001", "acc1", account.id)
    competitor_service.delete_video("u_001", "acc1", video.id)

    assert competitor_service.list_accounts("u_001", "acc1") == []
    assert competitor_service.list_videos("u_001", "acc1") == []


def test_add_douyin_account_extracts_sec_user_id_from_profile_url(
    competitor_service,
):
    account, workflow = competitor_service.add_account(
        "u_001",
        "acc1",
        "https://www.douyin.com/user/MS4wLjABAAA-test?relation=1&vid=123",
    )

    assert account.sec_user_id == "MS4wLjABAAA-test"
    assert competitor_service.repository.refresh_context(workflow.id)["secUserId"] == (
        "MS4wLjABAAA-test"
    )


def test_add_targets_persists_workflow_before_foreign_key_target():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    init_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    service = CompetitorMonitoringService(session_factory=factory)

    account, account_workflow = service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/fk-order"
    )
    video, video_workflow = service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/fk-order"
    )

    assert account.active_workflow_id == account_workflow.id
    assert video.active_workflow_id == video_workflow.id
    with factory() as session:
        assert session.get(WorkflowRecord, account_workflow.id) is not None
        assert session.get(WorkflowRecord, video_workflow.id) is not None

    service.complete_refresh(
        account_workflow.id,
        NormalizedCompetitor(platform="dy", metrics={"followers": 10}),
    )
    refresh_workflow, is_new = service.create_refresh(
        "u_001", "acc1", "account", account.id, "manual"
    )

    assert is_new is True
    refreshed_account = service.get_account("u_001", "acc1", account.id)
    assert refreshed_account.active_workflow_id == refresh_workflow.id
    with factory() as session:
        assert session.get(WorkflowRecord, refresh_workflow.id) is not None


@pytest.mark.parametrize(
    ("constraint_name", "expected"),
    [
        ("uq_competitor_accounts_account_url", True),
        ("uq_competitor_videos_account_url", True),
        ("competitor_accounts_active_workflow_id_fkey", False),
        (None, False),
    ],
)
def test_only_target_unique_constraints_are_classified_as_duplicates(
    constraint_name, expected
):
    original = RuntimeError("database constraint violation")
    original.diag = SimpleNamespace(constraint_name=constraint_name)
    error = IntegrityError("INSERT", {}, original)

    assert competitor_repository._is_duplicate_target_error(error) is expected


def test_duplicate_and_cross_account_targets_are_not_exposed(competitor_service):
    account, _workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/a"
    )
    with pytest.raises(DuplicateCompetitorTarget):
        competitor_service.add_account(
            "u_001", "acc1", "https://www.douyin.com/user/a"
        )
    with pytest.raises(CompetitorTargetNotFound):
        competitor_service.delete_account("u_001", "acc2", account.id)


def test_equivalent_public_urls_are_canonicalized_before_duplicate_check(competitor_service):
    first, _workflow = competitor_service.add_video(
        "u_001",
        "acc1",
        "https://WWW.DOUYIN.COM/video/1/?utm_source=share#detail",
    )

    assert first.content_url == "https://www.douyin.com/video/1"
    with pytest.raises(DuplicateCompetitorTarget):
        competitor_service.add_video(
            "u_001", "acc1", "https://www.douyin.com/video/1"
        )


def test_refresh_workflow_heartbeats_while_crawler_is_running():
    class FakeService:
        def __init__(self):
            self.touches = 0

        async def execute_refresh(self, workflow_id, **_options):
            assert workflow_id == "wf_heartbeat"
            await asyncio.sleep(0.02)
            return {"targetId": "cv_1"}

        def touch_refresh(self, workflow_id, _now):
            assert workflow_id == "wf_heartbeat"
            self.touches += 1
            return True

    fake = FakeService()
    result = asyncio.run(
        CompetitorRefreshWorkflow(
            "wf_heartbeat",
            {"_competitor_service": fake, "_heartbeat_seconds": 0.001},
        ).execute()
    )

    assert result == {"targetId": "cv_1"}
    assert fake.touches > 0


def test_transient_heartbeat_failure_does_not_override_successful_refresh():
    class FakeService:
        def __init__(self):
            self.touches = 0

        async def execute_refresh(self, _workflow_id, **_options):
            await asyncio.sleep(0.02)
            return {"targetId": "cv_1"}

        def touch_refresh(self, _workflow_id, _now):
            self.touches += 1
            if self.touches == 1:
                raise RuntimeError("temporary database error")
            return True

    fake = FakeService()
    result = asyncio.run(
        CompetitorRefreshWorkflow(
            "wf_heartbeat_retry",
            {"_competitor_service": fake, "_heartbeat_seconds": 0.001},
        ).execute()
    )

    assert result == {"targetId": "cv_1"}
    assert fake.touches > 1


def test_repeated_refresh_reuses_active_workflow(competitor_service):
    video, first = competitor_service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/1"
    )

    second, second_is_new = competitor_service.create_refresh(
        "u_001", "acc1", "video", video.id, "manual"
    )

    assert second.id == first.id
    assert second_is_new is False


def test_successful_refresh_writes_snapshot_and_delta(competitor_service):
    video, first = competitor_service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/1"
    )
    competitor_service.complete_refresh(
        first.id,
        NormalizedCompetitor(
            platform="dy",
            platform_content_id="1",
            title="第一版",
            metrics={"likes": 10, "comments": 2},
        ),
    )
    second, is_new = competitor_service.create_refresh(
        "u_001", "acc1", "video", video.id, "manual"
    )
    assert is_new is True
    refreshed = competitor_service.complete_refresh(
        second.id,
        NormalizedCompetitor(
            platform="dy",
            platform_content_id="1",
            title="第二版",
            metrics={"likes": 15, "comments": None},
        ),
    )

    assert refreshed.likes == 15
    assert refreshed.comments is None
    assert refreshed.delta_metrics == {"likes": 5}
    with competitor_service.session_factory() as session:
        snapshots = session.query(CompetitorSnapshotRecord).order_by(
            CompetitorSnapshotRecord.id
        ).all()
        assert [item.metrics for item in snapshots] == [
            {"likes": 10, "comments": 2},
            {"likes": 15, "comments": None},
        ]


def test_failed_refresh_keeps_last_successful_metrics(competitor_service):
    video, workflow = competitor_service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/1"
    )
    competitor_service.complete_refresh(
        workflow.id,
        NormalizedCompetitor(platform="dy", metrics={"likes": 20}),
    )
    retry, _is_new = competitor_service.create_refresh(
        "u_001", "acc1", "video", video.id, "manual"
    )

    competitor_service.fail_refresh(
        retry.id, "credentials_expired", "平台登录凭证失效"
    )
    saved = competitor_service.get_video("u_001", "acc1", video.id)

    assert saved.likes == 20
    assert saved.refresh_status == "failed"
    assert saved.refresh_error_code == "credentials_expired"
    assert saved.active_workflow_id is None


def test_execute_account_refresh_persists_creator_metrics_with_additive_raw_data(
    competitor_service,
):
    account, workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/account-1"
    )
    calls = []

    class FakeCrawler:
        async def crawl_by_creator(self, **options):
            calls.append(options)
            return CrawlResult(
                platform="dy",
                crawl_type="creator",
                contents=[
                    {
                        "aweme_id": str(index),
                        "title": f"视频 {index}",
                        "aweme_url": f"https://www.douyin.com/video/{index}",
                        "cover_url": f"https://cdn.example.test/{index}.jpg",
                        "create_time": 1_700_000_000 + index,
                        "liked_count": index,
                        "comment_count": index + 1,
                    }
                    for index in range(1, 12)
                ],
                comments=[{"comment_id": "must-not-persist"}],
                creators=[
                    {
                        "display_name": "真实博主",
                        "profile_url": "https://www.douyin.com/user/account-1",
                        "avatar": "https://cdn.example.test/avatar.jpg",
                        "bio": "账号简介",
                        "fans_count": 12_345,
                        "following_count": 67,
                        "works_count": 89,
                        "liked_count": 456_789,
                        "raw_data": {
                            "follower_count": 12_345,
                            "signature": "账号简介",
                        },
                    }
                ],
            )

    class FakeCookiePool:
        def candidates(self, platform):
            assert platform == "dy"
            return ("safe-cookie",)

    result = asyncio.run(
        competitor_service.execute_refresh(
            workflow.id,
            crawler_service=FakeCrawler(),
            cookie_pool_loader=lambda: FakeCookiePool(),
            runtime_options_loader=lambda platform: {"headless": True},
        )
    )

    saved = competitor_service.get_account("u_001", "acc1", account.id)
    assert result["targetType"] == "account"
    assert saved.name == "真实博主"
    assert saved.bio == "账号简介"
    assert saved.avatar_url == "https://cdn.example.test/avatar.jpg"
    assert saved.followers == 12_345
    assert saved.following == 67
    assert saved.works == 89
    assert saved.liked == 456_789
    assert saved.delta_metrics == {}
    assert len(saved.latest_videos) == 11
    assert [item["platformContentId"] for item in saved.latest_videos] == [
        str(index) for index in range(1, 12)
    ]
    assert saved.new_videos == []
    assert callable(calls[0].pop("on_partial_result"))
    assert calls == [
        {
            "creator_url": "https://www.douyin.com/user/account-1",
            "cookies": "safe-cookie",
            "headless": True,
            "max_notes_count": 20,
            "max_detail_count": 5,
            "detail_concurrency": 2,
            "enable_comments": False,
            "enable_sub_comments": False,
        }
    ]
    with competitor_service.session_factory() as session:
        first_snapshot = session.query(CompetitorSnapshotRecord).one()
        assert first_snapshot.items == saved.latest_videos

    second, is_new = competitor_service.create_refresh(
        "u_001", "acc1", "account", account.id, "manual"
    )
    assert is_new is True

    class IncrementalCrawler:
        async def crawl_by_creator(self, **_options):
            return CrawlResult(
                platform="dy",
                crawl_type="creator",
                creators=[{"display_name": "真实博主", "fans_count": 12_400}],
                contents=[
                    {
                        "aweme_id": "12",
                        "title": "最新发布",
                        "aweme_url": "https://www.douyin.com/video/12",
                        "cover_url": "https://cdn.example.test/12.jpg",
                        "create_time": int(datetime.now(UTC).timestamp()),
                        "liked_count": 88,
                        "collected_count": 12,
                    },
                    *[
                        {
                            "aweme_id": str(index),
                            "title": f"视频 {index}",
                            "aweme_url": f"https://www.douyin.com/video/{index}",
                        }
                        for index in range(1, 10)
                    ],
                ],
            )

    asyncio.run(
        competitor_service.execute_refresh(
            second.id,
            crawler_service=IncrementalCrawler(),
            cookie_pool_loader=lambda: FakeCookiePool(),
            runtime_options_loader=lambda platform: {},
        )
    )
    refreshed = competitor_service.get_account("u_001", "acc1", account.id)
    assert refreshed.new_videos == [refreshed.latest_videos[0]]
    assert refreshed.new_videos[0]["contentUrl"] == "https://www.douyin.com/video/12"
    trends = competitor_service.list_account_content_trends(
        "u_001", "acc1", account.id, days=7
    )
    recent_trend = next(item for item in trends if item["platformContentId"] == "12")
    assert recent_trend["points"][0]["metrics"] == {
        "likes": 88,
        "comments": None,
        "shares": None,
        "plays": None,
        "collects": 12,
    }
    with competitor_service.session_factory() as session:
        snapshots = session.query(CompetitorSnapshotRecord).order_by(
            CompetitorSnapshotRecord.id
        ).all()
        assert len(snapshots) == 2
        assert snapshots[0].items[0]["platformContentId"] == "1"
        assert snapshots[1].items[0]["platformContentId"] == "12"


def test_account_profile_is_persisted_before_creator_works_finish(
    competitor_service,
):
    account, workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/async-account"
    )
    observed = {}

    class FakeCrawler:
        async def crawl_by_creator(self, **options):
            options["on_partial_result"](
                CrawlResult(
                    platform="dy",
                    crawl_type="creator",
                    creators=[
                        {
                            "display_name": "先展示的博主",
                            "bio": "作品仍在刷新",
                            "fans_count": 321,
                        }
                    ],
                    creator_count=1,
                )
            )
            partial = competitor_service.get_account(
                "u_001", "acc1", account.id
            )
            observed.update(
                name=partial.name,
                bio=partial.bio,
                followers=partial.followers,
                refresh_status=partial.refresh_status,
                active_workflow_id=partial.active_workflow_id,
                latest_videos=partial.latest_videos,
            )
            return CrawlResult(
                platform="dy",
                crawl_type="creator",
                creators=[
                    {
                        "display_name": "先展示的博主",
                        "bio": "作品仍在刷新",
                        "fans_count": 321,
                    }
                ],
                contents=[
                    {
                        "aweme_id": "work-1",
                        "title": "稍后补齐的作品",
                        "aweme_url": "https://www.douyin.com/video/work-1",
                    }
                ],
            )

    class FakeCookiePool:
        def candidates(self, _platform):
            return ("safe-cookie",)

    asyncio.run(
        competitor_service.execute_refresh(
            workflow.id,
            crawler_service=FakeCrawler(),
            cookie_pool_loader=lambda: FakeCookiePool(),
            runtime_options_loader=lambda _platform: {},
        )
    )

    assert observed == {
        "name": "先展示的博主",
        "bio": "作品仍在刷新",
        "followers": 321,
        "refresh_status": "running",
        "active_workflow_id": workflow.id,
        "latest_videos": [],
    }
    completed = competitor_service.get_account("u_001", "acc1", account.id)
    assert completed.refresh_status == "succeeded"
    assert completed.active_workflow_id is None
    assert completed.latest_videos[0]["platformContentId"] == "work-1"


def test_execute_video_refresh_crawls_detail_and_persists_result(competitor_service):
    video, workflow = competitor_service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/1"
    )
    calls = []

    class FakeCrawler:
        async def crawl_by_detail(self, **options):
            calls.append(options)
            return CrawlResult(
                platform="dy",
                crawl_type="detail",
                contents=[
                    {
                        "aweme_id": "1",
                        "title": "真实视频",
                        "liked_count": 88,
                        "comment_count": 6,
                    }
                ],
            )

    class FakeCookiePool:
        def candidates(self, platform):
            assert platform == "dy"
            return ("safe-cookie",)

    result = __import__("asyncio").run(
        competitor_service.execute_refresh(
            workflow.id,
            crawler_service=FakeCrawler(),
            cookie_pool_loader=lambda: FakeCookiePool(),
            runtime_options_loader=lambda platform: {"headless": True},
        )
    )

    saved = competitor_service.get_video("u_001", "acc1", video.id)
    assert result["targetType"] == "video"
    assert saved.title == "真实视频"
    assert saved.likes == 88
    assert calls == [
        {
            "content_url": "https://www.douyin.com/video/1",
            "cookies": "safe-cookie",
            "headless": True,
            "enable_comments": False,
            "enable_sub_comments": False,
        }
    ]


def test_tikhub_account_refresh_limits_recent_list_and_detail_hydration(
    competitor_service,
):
    account, workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/limited-account"
    )
    calls = []

    class FakeCrawler:
        async def crawl_by_creator(self, **options):
            calls.append(options)
            return CrawlResult(
                platform="dy",
                crawl_type="creator",
                creators=[{"display_name": "受限抓取账号", "fans_count": 12}],
            )

    asyncio.run(
        competitor_service.execute_refresh(
            workflow.id,
            crawler_service=FakeCrawler(),
        )
    )

    assert competitor_service.get_account("u_001", "acc1", account.id).followers == 12
    assert calls[0]["max_notes_count"] == 20
    assert calls[0]["max_detail_count"] == 5
    assert "detail_concurrency" not in calls[0]
    assert calls[0]["recent_since"].tzinfo is not None
    assert calls[0]["enable_comments"] is False


def test_execute_refresh_retries_transient_platform_failure(competitor_service):
    account, workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/retry-account"
    )
    attempts = []
    delays = []
    competitor_service.crawl_max_attempts = 3
    competitor_service.crawl_retry_backoff_seconds = 0.5

    async def fake_sleep(delay):
        delays.append(delay)

    competitor_service.retry_sleep = fake_sleep

    class FakeCrawler:
        async def crawl_by_creator(self, **_options):
            attempts.append("crawl")
            if len(attempts) == 1:
                raise CrawlerExecutionError(
                    "dy",
                    RuntimeError("unsafe-response-detail"),
                    CrawlResult(platform="dy", crawl_type="creator"),
                    failure=public_crawler_failure("platform_blocked"),
                )
            return CrawlResult(
                platform="dy",
                crawl_type="creator",
                creators=[{"display_name": "重试成功", "fans_count": 123}],
            )

    class FakeCookiePool:
        def candidates(self, _platform):
            return ("safe-cookie",)

    asyncio.run(
        competitor_service.execute_refresh(
            workflow.id,
            crawler_service=FakeCrawler(),
            cookie_pool_loader=lambda: FakeCookiePool(),
            runtime_options_loader=lambda _platform: {},
        )
    )

    saved = competitor_service.get_account("u_001", "acc1", account.id)
    assert saved.name == "重试成功"
    assert saved.followers == 123
    assert attempts == ["crawl", "crawl"]
    assert delays == [0.5]


def test_execute_refresh_retries_transient_execjs_process_exit(
    competitor_service,
):
    account, workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/retry-execjs"
    )
    attempts = []
    competitor_service.crawl_max_attempts = 2
    competitor_service.crawl_retry_backoff_seconds = 0
    ProcessExitedWithNonZeroStatus = type(
        "ProcessExitedWithNonZeroStatus",
        (RuntimeError,),
        {"__module__": "execjs._exceptions"},
    )

    class FakeCrawler:
        async def crawl_by_creator(self, **_options):
            attempts.append("crawl")
            if len(attempts) == 1:
                raise CrawlerExecutionError(
                    "dy",
                    ProcessExitedWithNonZeroStatus("unsafe stderr"),
                    CrawlResult(platform="dy", crawl_type="creator"),
                    failure=public_crawler_failure("runtime_incompatible"),
                )
            return CrawlResult(
                platform="dy",
                crawl_type="creator",
                creators=[{"display_name": "Node 重试成功", "fans_count": 456}],
            )

    class FakeCookiePool:
        def candidates(self, _platform):
            return ("safe-cookie",)

    asyncio.run(
        competitor_service.execute_refresh(
            workflow.id,
            crawler_service=FakeCrawler(),
            cookie_pool_loader=lambda: FakeCookiePool(),
            runtime_options_loader=lambda _platform: {},
        )
    )

    saved = competitor_service.get_account("u_001", "acc1", account.id)
    assert attempts == ["crawl", "crawl"]
    assert saved.refresh_status == "succeeded"
    assert saved.name == "Node 重试成功"
    assert saved.followers == 456


def test_execute_account_refresh_keeps_partial_creator_after_retries_exhausted(
    competitor_service,
):
    account, workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/partial-account"
    )
    competitor_service.crawl_max_attempts = 1

    class FakeCrawler:
        async def crawl_by_creator(self, **_options):
            raise CrawlerExecutionError(
                "dy",
                RuntimeError("unsafe-post-list-response"),
                CrawlResult(
                    platform="dy",
                    crawl_type="creator",
                    creators=[
                        {
                            "display_name": "已获取基本信息",
                            "bio": "作品列表失败也应保留",
                            "fans_count": 456,
                        }
                    ],
                ),
                failure=public_crawler_failure("platform_blocked"),
            )

    class FakeCookiePool:
        def candidates(self, _platform):
            return ("safe-cookie",)

    asyncio.run(
        competitor_service.execute_refresh(
            workflow.id,
            crawler_service=FakeCrawler(),
            cookie_pool_loader=lambda: FakeCookiePool(),
            runtime_options_loader=lambda _platform: {},
        )
    )

    saved = competitor_service.get_account("u_001", "acc1", account.id)
    assert saved.refresh_status == "succeeded"
    assert saved.name == "已获取基本信息"
    assert saved.bio == "作品列表失败也应保留"
    assert saved.followers == 456
    assert saved.latest_videos == []
