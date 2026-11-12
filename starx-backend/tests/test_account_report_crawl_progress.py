import asyncio
import json

import pytest

from app.services.account_report.collection.progress import (
    AccountReportCrawlProgressTracker,
    CrawlTarget,
)
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerFailure,
    CrawlerProgressEvent,
)
from app.services.mediaspider.service import MediaCrawlerService


class FakeProgressStore:
    def __init__(self, existing=None):
        self.merged = dict(existing or {})
        self.payloads = []

    def update_progress(
        self, _workflow_id, *, progress, current_stage, result_payload
    ):
        self.merged.update(result_payload)
        self.payloads.append(result_payload)


class RecoveringProgressStore(FakeProgressStore):
    def __init__(self, fail_attempts):
        super().__init__()
        self.fail_attempts = set(fail_attempts)
        self.attempts = 0

    def update_progress(self, *args, **kwargs):
        self.attempts += 1
        if self.attempts in self.fail_attempts:
            raise RuntimeError("headers={'Cookie':'persistence-log-sentinel'}")
        return super().update_progress(*args, **kwargs)


def test_tracker_translates_creator_and_keyword_modes_to_account_report_language():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="creator",
                action="creator_started",
                status="running",
                message="底层原始文案",
            ),
            platform_name="小红书",
            mode="creator",
        )
    )
    assert (
        tracker.snapshot()["current"]["message"]
        == "开始采集当前账号主页公开信息"
    )

    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="creator_discovered",
                status="running",
                message="底层原始文案",
                subject="行业账号",
            ),
            platform_name="小红书",
            mode="keyword",
        )
    )
    assert tracker.snapshot()["current"]["message"] == "发现行业公开账号"


def test_tracker_ignores_all_comment_progress_when_comment_reference_is_disabled():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1",
        store,
        [CrawlTarget("小红书", "xhs")],
        track_comments=False,
    )

    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="content_discovered",
                status="running",
                message="发现公开内容",
                contentCount=1,
                commentCount=7,
            )
        )
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="comments_updated",
                status="running",
                message="更新评论",
                contentCount=1,
                commentCount=9,
            )
        )
    )
    tracker.complete("xhs", content_count=1, creator_count=0, comment_count=9)

    snapshot = tracker.snapshot()
    assert snapshot["platformSummaries"][0]["commentCount"] == 0
    assert all(item["commentCount"] == 0 for item in snapshot["activities"])
    assert all(item["action"] != "comments_updated" for item in snapshot["activities"])


def test_creator_url_notice_is_skipped_but_does_not_mark_platform_failed():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )

    tracker.notice(
        "dy",
        mode="creator",
        code="creator_url_invalid",
    )

    snapshot = store.merged["crawlProgress"]
    summary = snapshot["platformSummaries"][0]
    assert summary["status"] == "pending"
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"
    assert summary["noticeMessage"] == "当前账号主页链接无效，已跳过主页公开信息采集"
    assert (
        summary["noticeSuggestion"]
        == "请在账号档案中填写该平台真实、完整的当前账号主页链接"
    )
    assert snapshot["current"]["status"] == "skipped"
    assert snapshot["current"]["action"] == "creator_skipped"


def test_platform_completes_after_creator_notice_and_keeps_notice_visible():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )
    tracker.notice("dy", mode="creator", code="creator_url_invalid")

    tracker.complete("dy", content_count=4, creator_count=0, comment_count=8)

    summary = store.merged["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "completed"
    assert summary["contentCount"] == 4
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"


def test_real_failure_and_creator_notice_remain_separate():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )
    tracker.notice("dy", mode="creator", code="creator_url_invalid")
    tracker.fail(
        "dy",
        mode="keyword",
        failure=CrawlerFailure(
            code="browser_timeout",
            message="平台页面响应超时",
            suggestion="请稍后重试",
        ),
    )

    summary = store.merged["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "failed"
    assert summary["failureCode"] == "browser_timeout"
    assert summary["noticeCode"] == "creator_url_invalid"


def test_tracker_rejects_unknown_notice_codes_without_persisting_text():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )

    with pytest.raises(ValueError, match="unsupported account report notice code"):
        tracker.notice("dy", mode="creator", code="forged-notice-sentinel")

    assert "forged-notice-sentinel" not in json.dumps(store.merged, ensure_ascii=False)


def test_tracker_keeps_last_thirty_events_and_never_persists_credentials():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )

    for index in range(35):
        asyncio.run(
            tracker.record(
                CrawlerProgressEvent(
                    platform="xhs",
                    crawlType="search",
                    action="content_discovered",
                    status="running",
                    message="发现公开内容",
                    contentTitle=f"内容 {index} cookie=secret",
                    contentCount=index + 1,
                )
            )
        )

    snapshot = store.payloads[-1]["crawlProgress"]
    assert len(snapshot["activities"]) == 30
    assert snapshot["activities"][-1]["sequence"] == 35
    assert "secret" not in json.dumps(snapshot, ensure_ascii=False).lower()


def test_tracker_merges_platform_failure_and_preserves_existing_result_payload():
    store = FakeProgressStore(existing={"reportVersion": 2})
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )
    tracker.fail(
        "dy",
        mode="keyword",
        failure=CrawlerFailure(
            code="credentials_expired",
            message="登录凭证失效或未生效",
            suggestion="更新该平台 Cookie 并重启服务",
        ),
    )

    assert store.merged["reportVersion"] == 2
    assert (
        store.merged["crawlProgress"]["platformSummaries"][0]["failureCode"]
        == "credentials_expired"
    )


def test_tracker_merges_only_consecutive_updates_for_the_same_content():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )

    for count in (1, 2):
        asyncio.run(
            tracker.record(
                CrawlerProgressEvent(
                    platform="xhs",
                    crawlType="search",
                    action="content_discovered",
                    status="running",
                    message="发现公开内容",
                    subject="公开内容",
                    contentTitle="同一内容",
                    contentCount=count,
                )
            )
        )

    snapshot = store.payloads[-1]["crawlProgress"]
    assert len(snapshot["activities"]) == 1
    assert snapshot["activities"][0]["sequence"] == 2
    assert snapshot["activities"][0]["contentCount"] == 2


def test_tracker_sanitizes_subject_title_failure_and_summary_text():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="creator",
                action="creator_started",
                status="running",
                message="开始采集 https://example.com/profile?token=unsafe",
                subject="联系 13812345678 或 person@example.com，vx:unsafe_handle",
                contentTitle="cookie=unsafe-secret",
            )
        )
    )
    tracker.fail(
        "xhs",
        mode="creator",
        failure=CrawlerFailure(
            code="crawler_failed",
            message="Cookie=unsafe-secret https://example.com/fail",
            suggestion="联系 person@example.com",
        ),
    )

    serialized = json.dumps(store.merged["crawlProgress"], ensure_ascii=False).lower()
    assert "unsafe" not in serialized
    assert "13812345678" not in serialized
    assert "person@example.com" not in serialized
    assert "https://" not in serialized
    assert "cookie=" not in serialized


def test_tracker_does_not_regress_cumulative_counts_with_sparse_events():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )

    for action, content_count in (("content_discovered", 5), ("comments_updated", 0)):
        asyncio.run(
            tracker.record(
                CrawlerProgressEvent(
                    platform="xhs",
                    crawlType="search",
                    action=action,
                    status="running",
                    message="更新公开采集计数",
                    contentCount=content_count,
                    commentCount=1 if action == "comments_updated" else 0,
                )
            )
        )

    summary = store.merged["crawlProgress"]["platformSummaries"][0]
    assert summary["contentCount"] == 5
    assert summary["commentCount"] == 1
    assert store.merged["crawlProgress"]["activities"][-1]["contentCount"] == 5


def test_tracker_fail_closed_replaces_multi_credentials_and_stringified_headers():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="content_discovered",
                status="running",
                message=(
                    'headers={"Cookie":"cookie-sentinel; csrf=csrf-sentinel",'
                    '"Authorization":"Bearer bearer-sentinel"}'
                ),
                contentTitle='Cookies="title-sentinel; second-title-sentinel"',
            )
        )
    )
    tracker.fail(
        "xhs",
        mode="keyword",
        failure=CrawlerFailure.model_construct(
            code="credentials_expired",
            message='Cookies="failure-sentinel; second-failure-sentinel"',
            suggestion="secret=suggestion-sentinel; session=session-sentinel",
        ),
    )

    snapshot = store.merged["crawlProgress"]
    serialized = json.dumps(snapshot, ensure_ascii=False).lower()
    for sentinel in (
        "cookie-sentinel",
        "csrf-sentinel",
        "bearer-sentinel",
        "title-sentinel",
        "second-title-sentinel",
        "failure-sentinel",
        "second-failure-sentinel",
        "suggestion-sentinel",
        "session-sentinel",
    ):
        assert sentinel not in serialized
    assert snapshot["activities"][0]["message"] == "发现公开内容"
    assert snapshot["activities"][0]["contentTitle"] == "[敏感信息已移除]"
    assert snapshot["current"]["message"] == "登录凭证失效或未生效"
    assert (
        snapshot["platformSummaries"][0]["failureMessage"]
        == "登录凭证失效或未生效"
    )


def test_tracker_discards_all_suspected_request_headers_and_uses_action_message():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="content_discovered",
                status="running",
                message=(
                    'headers={"X-API-Key":"api-header-sentinel",'
                    '"Referer":"https://example.test/referer-header-sentinel",'
                    '"User-Agent":"user-agent-header-sentinel",'
                    '"Set-Cookie":"set-cookie-header-sentinel"}'
                ),
                contentTitle='"X-API-Key":"title-api-header-sentinel"',
            )
        )
    )

    snapshot = store.merged["crawlProgress"]
    serialized = json.dumps(snapshot, ensure_ascii=False).lower()
    for sentinel in (
        "api-header-sentinel",
        "referer-header-sentinel",
        "user-agent-header-sentinel",
        "set-cookie-header-sentinel",
        "title-api-header-sentinel",
    ):
        assert sentinel not in serialized
    assert snapshot["current"]["message"] == "发现公开内容"
    assert snapshot["current"]["contentTitle"] == "[敏感信息已移除]"


def test_tracker_drops_raw_creator_ids_and_masks_nickname_subjects_again():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )

    for subject in (
        "sec_user_id=MS4wLjABAAAA-raw-id-sentinel-1234567890",
        "测试博主",
    ):
        asyncio.run(
            tracker.record(
                CrawlerProgressEvent(
                    platform="xhs",
                    crawlType="creator",
                    action="creator_discovered",
                    status="running",
                    message="发现公开博主",
                    subject=subject,
                    creatorCount=1,
                )
            )
        )

    activities = store.merged["crawlProgress"]["activities"]
    assert activities[-2]["subject"] == ""
    assert activities[-1]["subject"] == "测***主"
    assert "raw-id-sentinel" not in json.dumps(
        store.merged["crawlProgress"], ensure_ascii=False
    )


def test_tracker_rejects_raw_ids_from_every_persisted_free_text_field():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="creator",
                action="creator_discovered",
                status="running",
                message="user_id=message-id-sentinel-1234567890",
                subject="creator_id=subject-id-sentinel-1234567890",
                contentTitle="sec_user_id=title-id-sentinel-1234567890",
                creatorCount=1,
            )
        )
    )
    tracker.fail(
        "xhs",
        mode="creator",
        failure=CrawlerFailure.model_construct(
            code="browser_timeout",
            message="uid=failure-id-sentinel-1234567890",
            suggestion="creator_id=suggestion-id-sentinel-1234567890",
        ),
    )

    snapshot = store.merged["crawlProgress"]
    serialized = json.dumps(snapshot, ensure_ascii=False).lower()
    for sentinel in (
        "message-id-sentinel",
        "subject-id-sentinel",
        "title-id-sentinel",
        "failure-id-sentinel",
        "suggestion-id-sentinel",
    ):
        assert sentinel not in serialized
    assert snapshot["activities"][0]["message"] == "读取账号公开资料"
    assert snapshot["activities"][0]["subject"] == ""
    assert snapshot["activities"][0]["contentTitle"] == "[敏感信息已移除]"


def test_tracker_uses_fixed_failure_copy_for_legal_code_with_malicious_text():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )
    tracker.fail(
        "dy",
        mode="keyword",
        failure=CrawlerFailure.model_construct(
            code="browser_timeout",
            message="恶意 failure message sentinel",
            suggestion="恶意 failure suggestion sentinel",
        ),
    )

    snapshot = store.merged["crawlProgress"]
    serialized = json.dumps(snapshot, ensure_ascii=False).lower()
    assert "failure message sentinel" not in serialized
    assert "failure suggestion sentinel" not in serialized
    assert snapshot["platformSummaries"][0]["failureCode"] == "browser_timeout"
    assert snapshot["platformSummaries"][0]["failureMessage"] == "平台页面响应超时"
    assert snapshot["platformSummaries"][0]["failureSuggestion"] == "请稍后重试"


def test_tracker_safely_downgrades_forged_failure_without_raising_validation_error():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    forged = CrawlerFailure.model_construct(
        code="forged_failure_code",
        message="forged-message-sentinel",
        suggestion="forged-suggestion-sentinel",
    )

    tracker.fail("xhs", mode="keyword", failure=forged)

    serialized = json.dumps(store.merged["crawlProgress"], ensure_ascii=False)
    assert "forged" not in serialized
    summary = store.merged["crawlProgress"]["platformSummaries"][0]
    assert summary["failureCode"] == "crawler_failed"
    assert summary["failureMessage"] == "平台采集失败"


def test_tracker_preserves_safe_keyword_and_known_creator_started_subjects():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    keyword_callback = tracker.callback("小红书", "keyword")
    creator_callback = tracker.callback("小红书", "creator")

    asyncio.run(
        keyword_callback(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="keyword_started",
                status="running",
                message="开始关键词采集",
                subject="美食、探店",
            )
        )
    )
    asyncio.run(
        creator_callback(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="creator",
                action="creator_started",
                status="running",
                message="开始博主主页采集",
                subject=(
                    "https://www.xiaohongshu.com/user/profile/raw-id-sentinel"
                    "?token=creator-subject-sentinel"
                ),
            )
        )
    )

    activities = store.merged["crawlProgress"]["activities"]
    assert activities[-2]["subject"] == "美食、探店"
    assert activities[-1]["subject"] == "小红书账号主页"
    assert "sentinel" not in json.dumps(store.merged, ensure_ascii=False)


def test_progress_event_and_credentials_missing_summary_support_skipped_status():
    event = CrawlerProgressEvent(
        platform="xhs",
        crawlType="search",
        action="run_failed",
        status="skipped",
        message="跳过平台采集",
    )
    assert event.status == "skipped"

    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    tracker.fail(
        "xhs",
        mode="configuration",
        failure=CrawlerFailure(
            code="credentials_missing",
            message="malicious",
            suggestion="malicious",
        ),
    )
    snapshot = store.merged["crawlProgress"]
    assert snapshot["platformSummaries"][0]["status"] == "skipped"
    assert snapshot["current"]["status"] == "skipped"


def test_constructor_persistence_failure_is_isolated_and_next_write_recovers(caplog):
    store = RecoveringProgressStore({1})
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )

    tracker.set_stage(progress=15, current_stage="creator_crawling")

    assert store.payloads[-1]["crawlProgress"]["platformSummaries"]
    assert "persistence-log-sentinel" not in caplog.text


def test_set_stage_persistence_failure_is_isolated_and_record_recovers():
    store = RecoveringProgressStore({2})
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    tracker.set_stage(progress=15, current_stage="creator_crawling")

    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="creator",
                action="creator_started",
                status="running",
                message="开始博主主页采集",
            )
        )
    )

    assert store.payloads[-1]["crawlProgress"]["current"]["action"] == "creator_started"


def test_record_persistence_failure_keeps_state_for_complete_recovery():
    store = RecoveringProgressStore({2})
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="content_discovered",
                status="running",
                message="发现公开内容",
                contentCount=3,
            )
        )
    )

    tracker.complete("xhs", content_count=3, creator_count=0, comment_count=0)

    snapshot = store.payloads[-1]["crawlProgress"]
    assert snapshot["activities"][-1]["action"] == "content_discovered"
    assert snapshot["platformSummaries"][0]["contentCount"] == 3


def test_fail_persistence_failure_keeps_state_for_stage_recovery():
    store = RecoveringProgressStore({2})
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    tracker.fail(
        "xhs",
        mode="keyword",
        failure=CrawlerFailure(
            code="browser_timeout",
            message="malicious",
            suggestion="malicious",
        ),
    )

    tracker.set_stage(progress=70, current_stage="evidence_normalization")

    summary = store.payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["failureCode"] == "browser_timeout"
    assert summary["failureSuggestion"] == "请稍后重试"


def test_complete_persistence_failure_keeps_state_for_stage_recovery():
    store = RecoveringProgressStore({2})
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    tracker.complete("xhs", content_count=2, creator_count=1, comment_count=0)

    tracker.set_stage(progress=70, current_stage="evidence_normalization")

    summary = store.payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "completed"
    assert summary["contentCount"] == 2


def test_record_then_fail_keeps_observed_counts_in_summary_and_activity():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="content_discovered",
                status="running",
                message="发现公开内容",
                contentCount=5,
                creatorCount=2,
                commentCount=3,
            )
        )
    )
    tracker.fail(
        "xhs",
        mode="keyword",
        failure=CrawlerFailure(
            code="crawler_failed",
            message="平台采集失败",
            suggestion="请稍后重试",
        ),
    )

    snapshot = store.merged["crawlProgress"]
    summary = snapshot["platformSummaries"][0]
    assert (summary["contentCount"], summary["creatorCount"], summary["commentCount"]) == (
        5,
        2,
        3,
    )
    assert (
        snapshot["activities"][-1]["contentCount"],
        snapshot["activities"][-1]["creatorCount"],
        snapshot["activities"][-1]["commentCount"],
    ) == (5, 2, 3)


def test_record_then_complete_uses_max_observed_or_result_without_double_counting():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    asyncio.run(
        tracker.record(
            CrawlerProgressEvent(
                platform="xhs",
                crawlType="search",
                action="run_completed",
                status="completed",
                message="平台采集完成",
                contentCount=5,
                creatorCount=2,
                commentCount=3,
            )
        )
    )
    tracker.complete(
        "xhs",
        content_count=4,
        creator_count=3,
        comment_count=2,
    )

    summary = store.merged["crawlProgress"]["platformSummaries"][0]
    assert (summary["contentCount"], summary["creatorCount"], summary["commentCount"]) == (
        5,
        3,
        3,
    )


def test_media_crawler_service_forwards_public_callback_to_tracker():
    async def runner(config, on_progress=None):
        assert on_progress is not None
        await on_progress(
            CrawlerProgressEvent(
                platform=config.platform,
                crawlType="search",
                action="content_discovered",
                status="running",
                message="发现公开内容",
                contentTitle="真实服务边界样本",
                contentCount=1,
            )
        )
        return CrawlResult(platform=config.platform, crawl_type="search", content_count=1)

    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )
    service = MediaCrawlerService(runner=runner)
    asyncio.run(
        service.crawl_by_keyword(
            keywords=["样本"],
            platform="xhs",
            cookies="safe-runtime-cookie",
            on_progress=tracker.callback("小红书", "keyword"),
        )
    )

    assert store.merged["crawlProgress"]["current"]["contentTitle"] == "真实服务边界样本"
