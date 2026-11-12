import asyncio
import json
import logging
import re
from types import SimpleNamespace

import pytest

from app.services.account_report.collection.keyword_parallel import (
    merge_keyword_results,
)
from app.services.account_report.domain.models import AccountReportPayload
from app.services.account_report.evidence import build_report_evidence
from app.services.account_report.workflows.report import _filter_report_candidates
from app.services.mediaspider.cookie_pool import RoundRobinCursor, WorkflowCookiePool
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerExecutionError,
    CrawlerFailure,
    CrawlerProgressEvent,
)
from app.services.mediaspider.vendor.user_hash import anonymize_user_id
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.workflow_store import WorkflowStore
from app.services.workflow.workflows.base import WorkflowRegister
from app.db.models import AccountRecord, KnowledgeBaseRecord, WorkflowRecord


def _report_payload(*, platforms=None, keywords=None, unsupported=None):
    return {
        "similarAccounts": [],
        "complianceRules": [
            {"riskLevel": "high", "expression": "第一", "reason": "绝对化", "suggestion": "较受欢迎"}
        ],
        "targetUserProfile": {
            "assumption": "假设产品为中价位通勤底妆。",
            "categories": [
                {
                    "categoryName": name,
                    "purchaseMotivation": "希望在具体通勤场景中获得可验证的解决方案。",
                    "maleProfile": {"applicable": True, "description": "处于稳定工作阶段，会在重要见面前寻找不费力的改善方式，并因真实示范建立信任。"},
                    "femaleProfile": {"applicable": True, "description": "日常通勤节奏紧凑，会在妆面失效时产生需求，更相信长期实测和具体适配建议。"},
                }
                for name in ("高压通勤者", "形象重建者", "重要场合准备者")
            ],
            "priorityRanking": {
                "rankedCategories": [
                    {
                        "categoryName": name,
                        "contentAttraction": "high",
                        "trustDifficulty": "medium",
                        "paymentLikelihood": "high",
                        "repurchaseLikelihood": "medium",
                        "reason": "场景明确且可通过内容持续验证。",
                    }
                    for name in ("高压通勤者", "形象重建者", "重要场合准备者")
                ],
                "priorityCategory": "高压通勤者",
                "priorityReason": "需求高频，内容关系容易延伸到复购。",
            },
            "positioningReminder": {
                "commonMisjudgment": "把所有关注底妆的人都当成高意向用户。",
                "hypothesisToValidate": "通勤前后对比是否会带来更多真实咨询。",
            },
        },
        "hotContents": [],
        "sourceMeta": {
            "platforms": platforms or ["小红书", "抖音"],
            "keywords": keywords if keywords is not None else ["通勤妆", "敏感肌", "底妆实测", "妆前打底"],
            "sampleCount": 2,
            "unsupportedPlatforms": unsupported or [],
        },
    }


class StubAI:
    token = "test"

    def __init__(
        self,
        report=None,
        keyword='{"keywords":["通勤妆","敏感肌","底妆实测","妆前打底"]}',
    ):
        self.keyword = keyword
        self.report = report or _report_payload()
        self.section_overrides = {}
        self.responses = []
        self.messages = []

    async def chat_completion(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        self.messages.append(prompt)
        if (
            "规划所有平台共用的 3–5 个检索短词" in prompt
            or "生成 3–5 个平台共用检索短词" in prompt
            or "生成恰好 4 个平台共用检索短词" in prompt
            or "中文社交媒体检索词规划员" in prompt
        ):
            return self.keyword
        if "禁止编造" in prompt and ("candidates" in prompt or '"index"' in prompt or "从 candidates" in prompt):
            override = self.section_overrides.get("similarAccounts")
            if override is not None:
                return override
            indexes = re.findall(r'"index":\s*(\d+)', prompt)
            unique = list(dict.fromkeys(int(value) for value in indexes))[:8]
            if not unique:
                unique = list(range(8))
            return json.dumps(
                [
                    {
                        "index": index,
                        "creatorHash": "",
                        "reason": f"测试重排相似原因{index}",
                    }
                    for index in unique
                ],
                ensure_ascii=False,
            )
        if "seedBlogger" in prompt and ("videoStyle" in prompt or "keywords" in prompt):
            override = self.section_overrides.get("similarAccounts")
            if override is not None:
                return override
            return (
                '{"videoStyle":"通勤底妆实测",'
                '"similarSearchKeyword":"底妆实测分享",'
                '"keywords":["通勤妆容测评","敏感肌底妆","底妆实测分享","敏感肌修护"]}'
            )
        if "社媒对标研究员" in prompt and "禁止编造" in prompt:
            override = self.section_overrides.get("similarAccounts")
            if override is not None:
                return override
            indexes = re.findall(r'"index":\s*(\d+)', prompt)
            unique = list(dict.fromkeys(int(value) for value in indexes))[:8]
            if not unique:
                unique = list(range(8))
            return json.dumps(
                [
                    {
                        "index": index,
                        "creatorHash": "",
                        "reason": f"测试重排相似原因{index}",
                    }
                    for index in unique
                ],
                ensure_ascii=False,
            )
        if "社媒对标研究员" in prompt and ("videoStyle" in prompt or "keywords" in prompt):
            override = self.section_overrides.get("similarAccounts")
            if override is not None:
                return override
            return (
                '{"videoStyle":"通勤底妆实测",'
                '"similarSearchKeyword":"底妆实测分享",'
                '"keywords":["通勤妆容测评","敏感肌底妆","底妆实测分享","敏感肌修护"]}'
            )
        if "对标账号顾问" in prompt or (
            "推荐" in prompt and "相似博主" in prompt
        ):
            override = self.section_overrides.get("similarAccounts")
            if override is not None:
                return override
            items = []
            for index, item in enumerate(self.report.get("similarAccounts") or []):
                platform = str(item.get("platform") or "抖音").strip()
                if platform in {"dy", "douyin"}:
                    platform = "抖音"
                if platform in {"xhs", "xiaohongshu"}:
                    platform = "小红书"
                if platform not in {"抖音", "小红书"}:
                    platform = "抖音"
                account_id = str(
                    item.get("accountId")
                    or item.get("creatorHash")
                    or f"stub-sim-{index}"
                ).strip()
                items.append(
                    {
                        "platform": platform,
                        "accountId": account_id,
                        "similarityReason": item.get("similarityReason") or "测试相似",
                    }
                )
            if not items:
                items = [
                    {
                        "platform": "抖音",
                        "accountId": "stub-sim-1",
                        "similarityReason": "默认相似",
                    }
                ]
            return json.dumps(items[:8], ensure_ascii=False)
        if "社媒对标质检员" in prompt or (
            "relatedCount" in prompt and "judgments" in prompt
        ):
            indexes = re.findall(r'"index":\s*(\d+)', prompt)
            unique = list(dict.fromkeys(int(value) for value in indexes)) or [0]
            return json.dumps(
                {
                    "judgments": [
                        {
                            "index": index,
                            "match": True,
                            "relatedCount": 6,
                            "score": 90,
                            "reason": "同属通勤底妆赛道，内容核心是底妆实测",
                        }
                        for index in unique
                    ]
                },
                ensure_ascii=False,
            )
        for key in (
            "similarAccounts",
            "complianceRules",
            "targetUserProfile",
            "hotContents",
        ):
            if f"本次只生成账号报告的 {key} 分块" in prompt:
                return self.section_overrides.get(
                    key,
                    json.dumps({key: self.report[key]}, ensure_ascii=False),
                )
        raise AssertionError("unexpected account report AI prompt")


class StubSimilarAccountResolver:
    async def resolve(self, profile_url: str = "", *, platform: str = "", account_id: str = ""):
        target = str(account_id or profile_url or "").strip() or "unknown"
        platform_name = str(platform or "抖音").strip() or "抖音"
        if platform_name in {"dy", "douyin"}:
            platform_name = "抖音"
        if platform_name in {"xhs", "xiaohongshu"}:
            platform_name = "小红书"
        host = "www.douyin.com/user" if platform_name == "抖音" else "www.xiaohongshu.com/user/profile"
        short_id = target.rstrip("/").rsplit("/", 1)[-1][:40] or "unknown"
        return {
            "name": f"昵称-{short_id}",
            "platform": platform_name,
            "profileUrl": (
                target
                if target.startswith("https://")
                else f"https://{host}/{short_id}"
            ),
            "avatarUrl": f"https://example.com/{short_id}.jpg",
            "description": "测试简介 通勤妆容 敏感肌底妆",
            "followers": 50_000,
            "follows": 1,
            "contentCount": 2,
            "totalLikes": 3,
            "ipLocation": "",
        }


class StubSettings:
    def __init__(
        self,
        *,
        max_notes_count=30,
        report_max_notes_per_keyword=2,
    ):
        self.max_notes_count = max_notes_count
        self.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD = report_max_notes_per_keyword

    def mediaspider_runtime_options(self, platform):
        return {
            "headless": True,
            "max_notes_count": self.max_notes_count,
            "enable_comments": True,
            "enable_sub_comments": True,
        }


class StubCookiePool:
    def __init__(self, cookies=None):
        self.cookies = (
            {
                "xhs": ("xhs-secret",),
                "dy": ("dy-secret",),
                "ks": ("ks-secret",),
            }
            if cookies is None
            else cookies
        )

    def has_cookies(self, platform):
        return bool(self.cookies.get(platform, ()))

    def candidates(self, platform):
        return tuple(self.cookies.get(platform, ()))


def _related_keyword(keywords) -> str:
    for item in list(keywords or []):
        text = str(item or "").strip()
        if text:
            return text
    return "通勤妆容"


def _with_relatedness(content: dict, keywords) -> dict:
    keyword = _related_keyword(keywords)
    next_item = dict(content)
    next_item.setdefault("source_keyword", keyword)
    title = str(next_item.get("title") or "").strip()
    if keyword not in title:
        next_item["title"] = f"{keyword}{title or '样本'}"
    next_item.setdefault("desc", f"{keyword}教程和方案")
    next_item.setdefault("liked_count", next_item.get("liked_count") or 1000)
    return next_item


def _call_pairs(crawler) -> list[tuple[str, str]]:
    return [(mode, platform) for mode, platform, _ in crawler.calls]


def _assert_creator_then_keyword(crawler, platforms: list[str]) -> None:
    pairs = _call_pairs(crawler)
    for platform in platforms:
        modes = [mode for mode, call_platform in pairs if call_platform == platform]
        assert "keyword" in modes
        if "creator" in modes:
            assert modes[0] == "creator"


class StubCrawler:
    def __init__(self, failures=None):
        self.calls = []
        self.failures = set(failures or [])

    async def crawl_by_creator(self, *, creator_url, on_progress=None, **options):
        platform = "xhs" if "xiaohongshu" in creator_url else "dy" if "douyin" in creator_url else "ks"
        self.calls.append(("creator", platform, options))
        if platform in self.failures or ("creator", platform) in self.failures:
            raise RuntimeError(f"Authorization: Bearer leaked Cookie={options['cookies']} url={creator_url}?token=secret")
        if on_progress:
            await on_progress(
                CrawlerProgressEvent(
                    platform=platform,
                    crawlType="creator",
                    action="creator_discovered",
                    status="running",
                    message="发现公开博主",
                    subject="测试博主",
                    creatorCount=1,
                )
            )
        titles = []
        for index in range(1, 11):
            row = {
                "title": f"通勤妆容实测{index}",
                "liked_count": 2000,
            }
            if platform == "xhs":
                row["note_id"] = f"{platform}-home-{index}"
            else:
                row["aweme_id"] = f"{platform}-home-{index}"
            titles.append(row)
        return CrawlResult(
            platform=platform,
            crawl_type="creator",
            creator_url=creator_url,
            contents=titles,
            creators=[{"id": f"owner-{platform}"}],
            creator_count=1,
        )

    async def crawl_by_keyword(self, *, keywords, platform, on_progress=None, **options):
        self.calls.append(("keyword", platform, options))
        if platform in self.failures or ("keyword", platform) in self.failures:
            raise RuntimeError(f"Cookie: {options['cookies']} https://example.com/path?session=secret")
        if on_progress:
            await on_progress(
                CrawlerProgressEvent(
                    platform=platform,
                    crawlType="search",
                    action="content_discovered",
                    status="running",
                    message="发现公开内容",
                    contentTitle="样本",
                    contentCount=8,
                )
            )
        keyword = _related_keyword(keywords)
        contents = []
        creators = []
        for index in range(8):
            user_id = f"peer-{platform}-{index}"
            content_id = f"post-{platform}" if index == 0 else f"post-{platform}-{index}"
            row = {
                "title": f"{keyword}实测样本{index}",
                "desc": f"{keyword}教程和方案",
                "source_keyword": keyword,
                "liked_count": 8000 - index,
                "nickname": f"同行{index}",
                "follower_count": 80_000 + index,
                "profile_url": (
                    f"https://www.xiaohongshu.com/user/profile/{user_id}"
                    if platform == "xhs"
                    else f"https://www.douyin.com/user/{user_id}"
                ),
            }
            if platform == "xhs":
                row["note_id"] = content_id
                row["user_id"] = user_id
            else:
                row["aweme_id"] = content_id
                row["content_id"] = content_id
                row["sec_user_id"] = user_id
            contents.append(row)
            creators.append(
                {
                    "sec_user_id" if platform != "xhs" else "user_id": user_id,
                    "nickname": f"同行{index}",
                    "profile_url": row["profile_url"],
                    "follower_count": 80_000 + index,
                    "search_channel": str(options.get("search_channel") or "general"),
                }
            )
        return CrawlResult(
            platform=platform,
            crawl_type="search",
            keywords=list(keywords),
            contents=contents,
            creators=creators,
            content_count=len(contents),
        )


class ClassifiedCrawler(StubCrawler):
    def __init__(self, failures=None, *, fail_all=False):
        super().__init__()
        self.classified_failures = dict(failures or {})
        self.fail_all = fail_all

    def _failure(self, mode, platform):
        if self.fail_all:
            return CrawlerFailure(
                code="credentials_expired",
                message="登录凭证失效或未生效",
                suggestion="更新该平台 Cookie 并重启服务",
            )
        return self.classified_failures.get((mode, platform))

    async def crawl_by_creator(self, *, creator_url, on_progress=None, **options):
        platform = "xhs" if "xiaohongshu" in creator_url else "dy" if "douyin" in creator_url else "ks"
        failure = self._failure("creator", platform)
        if failure:
            self.calls.append(("creator", platform, options))
            raise CrawlerExecutionError(
                platform,
                RuntimeError(f"Cookie={options['cookies']}"),
                CrawlResult(platform=platform, crawl_type="creator"),
                failure=failure,
            )
        return await super().crawl_by_creator(
            creator_url=creator_url,
            on_progress=on_progress,
            **options,
        )

    async def crawl_by_keyword(self, *, keywords, platform, on_progress=None, **options):
        failure = self._failure("keyword", platform)
        if failure:
            self.calls.append(("keyword", platform, options))
            raise CrawlerExecutionError(
                platform,
                RuntimeError(f"Cookie={options['cookies']}"),
                CrawlResult(platform=platform, crawl_type="search"),
                failure=failure,
            )
        return await super().crawl_by_keyword(
            keywords=keywords,
            platform=platform,
            on_progress=on_progress,
            **options,
        )


class StubStore:
    def __init__(self, platforms=None, links=None, *, reference_comments=False, section_key=""):
        self.context = {
            "account": {
                "id": "acc-1",
                "userId": "user-1",
                "name": "测试账号",
                "industry": "美妆",
                "platforms": platforms or ["小红书", "抖音"],
            },
            "knowledgeEnabled": True,
            "knowledgeContext": "产品: 底妆",
            "accountLinks": links
            or {
                "小红书": "https://www.xiaohongshu.com/user/profile/aaaaaaaaaaaaaaaaaaaaaaaa",
                "抖音": "https://www.douyin.com/user/MS4wLjABAAAATestSecUidValue12",
            },
            "referenceComments": reference_comments,
            "sectionKey": section_key,
            "similarTargetFansWan": None,
            "benchmarkAccounts": {},
        }
        self.progress = []
        self.result_payloads = []
        self.replacements = []
        self.section_updates = []
        self.seeded_benchmarks = []

    def account_report_context(self, _workflow_id):
        return self.context

    def seed_report_benchmark_manual_accounts(self, user_id, account_id, items):
        self.seeded_benchmarks.append((user_id, account_id, items))

    def update_progress(
        self, _workflow_id, *, progress, current_stage, result_payload=None, **_kwargs
    ):
        self.progress.append((progress, current_stage))
        if result_payload is not None:
            merged = dict(self.result_payloads[-1]) if self.result_payloads else {}
            merged.update(result_payload)
            self.result_payloads.append(merged)

    def replace_account_report(self, user_id, account_id, payload):
        self.replacements.append((user_id, account_id, payload))
        return SimpleNamespace(reportVersion=1)

    def update_account_report_sections(self, user_id, account_id, payload):
        self.section_updates.append((user_id, account_id, payload))
        return SimpleNamespace(reportVersion=2)


async def _execute(
    *,
    store,
    crawler,
    ai,
    settings=None,
    cookie_pool_loader=None,
    workflow_type="account_report",
    similar_account_resolver=None,
):
    async def benchmark_complete(prompt: str, *, stage: str) -> str:
        return await ai.chat_completion(messages=[{"role": "user", "content": prompt}])

    workflow_class = WorkflowRegister.get(workflow_type)
    workflow = workflow_class(
        "wf-1",
        {
            "_crawler_service": crawler,
            "_settings": settings or StubSettings(),
            "_cookie_pool_loader": cookie_pool_loader or (lambda: StubCookiePool()),
            "_similar_account_resolver": similar_account_resolver
            or StubSimilarAccountResolver(),
            "_benchmark_complete": benchmark_complete,
        },
    )
    workflow.store = store
    workflow.ai_service = ai
    return await workflow.execute()


def _report_evidence_from_prompt(prompt):
    return json.loads(prompt.split("输入：", 1)[1])["evidence"]


def _hot_contents_evidence_from_ai(ai):
    prompt = next(item for item in ai.messages if "hotContents 分块" in item)
    return _report_evidence_from_prompt(prompt)


def test_account_report_workflow_is_registered():
    assert WorkflowRegister.get("account_report").type == "account_report"


def test_tikhub_account_report_prepares_dashboard_before_keyword_search():
    from app.services.account_report.collection.dashboard_source import (
        DashboardAccountEvidence,
    )

    events = []

    class DashboardSourceStub:
        async def prepare(self, *, user_id, account_id, platform_names):
            events.append(("dashboard", list(platform_names)))
            assert user_id == "user-1"
            assert account_id == "acc-1"
            return DashboardAccountEvidence(
                results=[
                    CrawlResult(
                        platform="xhs",
                        crawl_type="creator",
                        creators=[
                            {
                                "user_id": "dashboard-owner",
                                "nickname": "看板账号",
                                "fans_count": 123,
                            }
                        ],
                        contents=[
                            {
                                "note_id": "dashboard-own-note",
                                "user_id": "dashboard-owner",
                                "title": "自己的看板作品",
                            }
                        ],
                    )
                ],
                owner_hashes={"dashboard-owner"},
            )

    class KeywordOnlyCrawler(StubCrawler):
        async def crawl_by_creator(self, **_kwargs):
            raise AssertionError("TikHub 账号报告不应再采集博主主页")

        async def crawl_by_keyword(self, **kwargs):
            events.append(("keyword", kwargs["platform"]))
            return await super().crawl_by_keyword(**kwargs)

    crawler = KeywordOnlyCrawler()
    store = StubStore(platforms=["小红书", "抖音"])
    workflow_class = WorkflowRegister.get("account_report")
    workflow = workflow_class(
        "wf-keyword-only",
        {
            "_crawler_service": crawler,
            "_settings": SimpleNamespace(
                social_retrieval_provider="tikhub",
                ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD=10,
                MEDIASPIDER_MAX_COMMENTS_COUNT=20,
            ),
            "_cookie_pool_loader": None,
            "_dashboard_source": DashboardSourceStub(),
        },
    )
    workflow.store = store
    workflow.ai_service = StubAI()

    asyncio.run(workflow.execute())

    assert events[0] == ("dashboard", ["小红书", "抖音"])
    assert [(mode, platform) for mode, platform, _ in crawler.calls] == [
        ("keyword", "xhs"),
        ("keyword", "dy"),
    ]
    evidence = _report_evidence_from_prompt(workflow.ai_service.messages[-1])
    assert [
        item["content_id"]
        for item in evidence["currentAccountEvidence"]["contents"]
    ] == ["dashboard-own-note"]


def test_each_visible_report_section_has_an_independent_workflow_class():
    expected = {
        "account_report_similar_accounts": "similarAccounts",
        "account_report_compliance_rules": "complianceRules",
        "account_report_target_user_profile": "targetUserProfile",
        "account_report_hot_contents": "hotContents",
    }

    for workflow_type, section_key in expected.items():
        workflow_class = WorkflowRegister.get(workflow_type)
        assert workflow_class.type == workflow_type
        assert workflow_class.section_key == section_key


def test_section_workflow_uses_its_declared_section_instead_of_input_payload():
    store = StubStore(section_key="hotContents")
    ai = StubAI()

    result = asyncio.run(
        _execute(
            store=store,
            crawler=StubCrawler(),
            ai=ai,
            workflow_type="account_report_target_user_profile",
        )
    )

    assert result["sectionKey"] == "targetUserProfile"
    assert set(store.section_updates[0][2]) == {
        "targetUserProfile",
        "targetUsers",
    }


def test_account_report_workflow_regenerates_only_requested_visible_section():
    store = StubStore(section_key="targetUserProfile")
    crawler = StubCrawler()
    ai = StubAI()

    result = asyncio.run(_execute(store=store, crawler=crawler, ai=ai))

    section_prompts = [prompt for prompt in ai.messages if "本次只生成账号报告的" in prompt]
    assert len(section_prompts) == 1
    assert "targetUserProfile 分块" in section_prompts[0]
    assert "规划所有平台共用的 3–5 个检索短词" not in "\n".join(ai.messages)
    assert "中文社交媒体检索词规划员" not in "\n".join(ai.messages)
    assert crawler.calls == []
    assert store.replacements == []
    assert len(store.section_updates) == 1
    payload = store.section_updates[0][2]
    assert set(payload) == {"targetUserProfile", "targetUsers"}
    assert payload["targetUserProfile"]["categories"]
    assert result == {"reportVersion": 2, "sectionKey": "targetUserProfile"}
    assert store.result_payloads[-1]["reportSectionsTotal"] == 1
    assert store.result_payloads[-1]["reportSectionsCompleted"] == ["targetUserProfile"]


def test_hot_contents_regenerate_reuses_candidate_pool_without_crawl():
    store = StubStore(section_key="hotContents", platforms=["抖音"], links={"抖音": ""})
    pool = []
    for keyword_index in range(4):
        keyword = f"词{keyword_index}"
        for rank in range(5):
            pool.append(
                {
                    "platform": "dy",
                    "contentId": f"k{keyword_index}-r{rank}",
                    "title": f"{keyword}-{rank}",
                    "summary": f"围绕{keyword}的干货教程与方案说明",
                    "contentType": "video",
                    "sourceKeyword": keyword,
                    "publicUrl": f"https://www.douyin.com/video/k{keyword_index}-r{rank}",
                    "coverUrl": f"https://cdn.example.test/k{keyword_index}-r{rank}.jpg",
                    "publishedAt": "2026-07-01T00:00:00Z",
                    "metrics": {
                        # 点赞接近，避免软爆款分位把后半截词整组滤掉导致不足 8 误触发翻页
                        "likedCount": 2000 - rank,
                        "collectedCount": 0,
                        "commentCount": 0,
                        "shareCount": 0,
                        "viewCount": 0,
                        "engagementScore": 0,
                        "hotScore": 0,
                    },
                }
            )
    store.context["hotContentsCandidatePool"] = pool
    store.context["reportKeywords"] = ["词0", "词1", "词2", "词3"]
    previous_ids = [
        f"k{keyword_index}-r{rank}"
        for keyword_index in range(4)
        for rank in range(2)
    ]
    store.context["previousHotContents"] = [
        {"platform": "dy", "contentId": content_id} for content_id in previous_ids
    ]
    crawler = StubCrawler()
    ai = StubAI(
        report=_report_payload(
            platforms=["抖音"],
            keywords=["词0", "词1", "词2", "词3"],
        )
    )

    result = asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=ai,
            workflow_type="account_report_hot_contents",
        )
    )

    assert crawler.calls == []
    assert "规划所有平台共用的 3–5 个检索短词" not in "\n".join(ai.messages)
    assert result["sectionKey"] == "hotContents"
    persisted = store.section_updates[0][2]["hotContents"]
    assert len(persisted) == 8
    assert {item["contentId"] for item in persisted} == {
        "k0-r2",
        "k0-r3",
        "k1-r2",
        "k1-r3",
        "k2-r2",
        "k2-r3",
        "k3-r2",
        "k3-r3",
    }
    assert all(
        item.get("coverUrl") == f"https://cdn.example.test/{item['contentId']}.jpg"
        for item in persisted
    )
    assert all(
        item.get("publicUrl") == f"https://www.douyin.com/video/{item['contentId']}"
        for item in persisted
    )
    assert store.section_updates[0][2]["sourceMeta"]["referenceDiscovery"]["hotContents"][
        "operations"
    ] == ["hot_contents_candidate_cache"]
    assert store.section_updates[0][2]["sourceMeta"]["hotContentsSearchPage"] == 2
    shown = {
        (item["platform"], item["contentId"])
        for item in store.section_updates[0][2]["sourceMeta"]["hotContentsShownKeys"]
    }
    assert shown >= {("dy", content_id) for content_id in previous_ids}
    assert shown >= {("dy", item["contentId"]) for item in persisted}


def test_hot_contents_regenerate_pages_search_when_candidate_pool_exhausted():
    """候选池不足以凑满下一批时，按关键词翻页补货，且不与历史批次重复。"""

    store = StubStore(
        section_key="hotContents",
        platforms=["抖音"],
        links={"抖音": "https://www.douyin.com/user/2"},
    )
    previous_ids = [f"old-{index}" for index in range(8)]
    store.context["hotContentsCandidatePool"] = [
        {
            "platform": "dy",
            "contentId": content_id,
            "title": content_id,
            "contentType": "video",
            "sourceKeyword": "词0",
            "metrics": {
                "likedCount": 100 - index,
                "collectedCount": 0,
                "commentCount": 0,
                "shareCount": 0,
                "viewCount": 0,
                "engagementScore": 0,
                "hotScore": 0,
            },
        }
        for index, content_id in enumerate(previous_ids)
    ]
    store.context["reportKeywords"] = ["词0", "词1", "词2", "词3"]
    store.context["previousHotContents"] = [
        {"platform": "dy", "contentId": content_id} for content_id in previous_ids
    ]
    store.context["hotContentsSearchPage"] = 2

    class PagingCrawler(StubCrawler):
        async def crawl_by_keyword(self, *, keywords, platform, on_progress=None, **options):
            self.calls.append(("keyword", platform, options))
            page = int(options.get("start_page") or 1)
            assert page >= 2
            keyword = keywords[0] if keywords else "词0"
            return CrawlResult(
                platform=platform,
                crawl_type="search",
                keywords=list(keywords),
                contents=[
                    {
                        "aweme_id": f"page{page}-{index}",
                        "content_id": f"page{page}-{index}",
                        "title": f"{keyword}翻页内容{index}",
                        "desc": f"围绕{keyword}的干货教程与方案说明{index}",
                        "liked_count": 2000 - index,
                        "create_time": 1720000000,
                        "source_keyword": keyword,
                    }
                    for index in range(12)
                ],
                content_count=12,
            )

    crawler = PagingCrawler()
    result = asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(
                report=_report_payload(
                    platforms=["抖音"],
                    keywords=["词0", "词1", "词2", "词3"],
                )
            ),
            workflow_type="account_report_hot_contents",
        )
    )

    assert result["sectionKey"] == "hotContents"
    assert crawler.calls
    assert min(int(call[2].get("start_page") or 0) for call in crawler.calls) == 2
    persisted = store.section_updates[0][2]["hotContents"]
    persisted_ids = {item["contentId"] for item in persisted}
    assert persisted_ids
    assert persisted_ids.isdisjoint(set(previous_ids))
    assert all(content_id.startswith("page") for content_id in persisted_ids)
    meta = store.section_updates[0][2]["sourceMeta"]
    assert "hot_contents_search_page" in meta["referenceDiscovery"]["hotContents"]["operations"]
    assert int(meta["hotContentsSearchPage"] or 0) >= 3
    shown_ids = {item["contentId"] for item in meta["hotContentsShownKeys"]}
    assert shown_ids >= set(previous_ids)
    assert shown_ids >= persisted_ids
    assert len(persisted) == 8


def test_hot_contents_regenerate_ignores_ai_picks_from_previous_batch():
    """换一批时即使模型回填上一批高赞 ID，也必须落到缓存里的下一批。"""

    store = StubStore(section_key="hotContents", platforms=["抖音"], links={"抖音": ""})
    pool = []
    for keyword_index in range(4):
        keyword = f"词{keyword_index}"
        for rank in range(5):
            pool.append(
                {
                    "platform": "dy",
                    "contentId": f"k{keyword_index}-r{rank}",
                    "title": f"{keyword}-{rank}",
                    "summary": f"围绕{keyword}的干货教程与方案说明",
                    "contentType": "video",
                    "sourceKeyword": keyword,
                    "publicUrl": f"https://www.douyin.com/video/k{keyword_index}-r{rank}",
                    "coverUrl": f"https://cdn.example.test/k{keyword_index}-r{rank}.jpg",
                    "publishedAt": "2026-07-01T00:00:00Z",
                    "metrics": {
                        "likedCount": 2000 - rank,
                        "collectedCount": 0,
                        "commentCount": 0,
                        "shareCount": 0,
                        "viewCount": 0,
                        "engagementScore": 0,
                        "hotScore": 0,
                    },
                }
            )
    store.context["hotContentsCandidatePool"] = pool
    store.context["reportKeywords"] = ["词0", "词1", "词2", "词3"]
    previous_ids = [
        f"k{keyword_index}-r{rank}"
        for keyword_index in range(4)
        for rank in range(2)
    ]
    store.context["previousHotContents"] = [
        {"platform": "dy", "contentId": content_id} for content_id in previous_ids
    ]
    ai = StubAI(
        report=_report_payload(
            platforms=["抖音"],
            keywords=["词0", "词1", "词2", "词3"],
        )
    )
    ai.section_overrides["hotContents"] = json.dumps(
        {
            "hotContents": [
                {
                    "platform": "dy",
                    "contentId": content_id,
                    "title": f"旧批次-{content_id}",
                    "selectionReason": "模型误回上一批",
                    "publicUrl": "",
                    "coverUrl": "",
                    "contentType": "video",
                    "tags": [],
                    "metrics": {},
                }
                for content_id in previous_ids
            ]
        },
        ensure_ascii=False,
    )

    result = asyncio.run(
        _execute(
            store=store,
            crawler=StubCrawler(),
            ai=ai,
            workflow_type="account_report_hot_contents",
        )
    )

    assert result["sectionKey"] == "hotContents"
    persisted = store.section_updates[0][2]["hotContents"]
    assert {item["contentId"] for item in persisted} == {
        "k0-r2",
        "k0-r3",
        "k1-r2",
        "k1-r3",
        "k2-r2",
        "k2-r3",
        "k3-r2",
        "k3-r3",
    }
    assert not any(item["contentId"] in previous_ids for item in persisted)
    assert "hotContentsCandidatePool" not in "\n".join(ai.messages)


def test_workflow_routes_account_and_industry_results_into_safe_ai_prompt():
    class SourceAwareCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            return CrawlResult(
                platform="xhs",
                crawl_type="creator",
                creator_url=creator_url,
                contents=[
                    {
                        "note_id": "own-1",
                        "user_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                        "title": "自己的内容",
                    }
                ],
                creators=[{"user_id": "aaaaaaaaaaaaaaaaaaaaaaaa", "nickname": "自己的账号"}],
            )

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            return CrawlResult(
                platform="xhs",
                crawl_type="search",
                keywords=list(keywords),
                contents=[
                    {
                        "note_id": "industry-1",
                        "user_id": "industry-account",
                        "title": "行业内容",
                        "source_keyword": _related_keyword(keywords),
                        "liked_count": 1200,
                    }
                ],
            )

    store = StubStore(
        platforms=["小红书"],
        links={
            "小红书": (
                "https://www.xiaohongshu.com/user/profile/aaaaaaaaaaaaaaaaaaaaaaaa"
                "?token=PROFILE_URL_SECRET"
            )
        },
    )
    store.context["knowledgeContext"] = (
        "产品: 底妆\n联系方式: 13800138000\n"
        "图片素材: https://secret.example/material.png"
    )
    ai = StubAI(report=_report_payload(platforms=["小红书"]))

    asyncio.run(_execute(store=store, crawler=SourceAwareCrawler(), ai=ai))

    prompt = next(item for item in ai.messages if "hotContents 分块" in item)
    payload = json.loads(prompt.split("输入：", 1)[1])
    evidence = payload["evidence"]
    assert [
        item["content_id"]
        for item in evidence["currentAccountEvidence"]["contents"]
    ] == ["own-1"]
    assert [
        item["content_id"]
        for item in evidence["industryEvidence"]["hotContents"]
    ] == ["industry-1"]
    assert "acc-1" not in prompt
    assert "user-1" not in prompt
    assert "PROFILE_URL_SECRET" not in prompt
    assert "13800138000" not in prompt
    assert "secret.example" not in prompt


def test_report_candidate_filter_allows_only_industry_hot_content_ids():
    evidence = build_report_evidence(
        [
            CrawlResult(
                platform="xhs",
                crawl_type="creator",
                contents=[
                    {"note_id": "own-1", "creator_hash": "owner", "title": "自己"}
                ],
            )
        ],
        [
            CrawlResult(
                platform="xhs",
                crawl_type="search",
                contents=[
                    {
                        "note_id": "industry-1",
                        "creator_hash": "peer",
                        "title": "行业",
                    }
                ],
            )
        ],
        {"owner"},
    )
    report_value = _report_payload(platforms=["小红书"])
    report_value["hotContents"] = [
        {
            "platform": "小红书",
            "contentId": content_id,
            "title": content_id,
            "selectionReason": "测试候选过滤",
        }
        for content_id in ("own-1", "industry-1", "invented-1")
    ]
    report = AccountReportPayload.model_validate(report_value)

    filtered = _filter_report_candidates(report, evidence)

    assert [item.content_id for item in filtered.hot_contents] == ["industry-1"]


def test_account_report_logs_complete_ai_responses_with_stage(caplog):
    ai = StubAI()

    with caplog.at_level(logging.INFO, logger="app.services.account_report.workflows.base"):
        asyncio.run(_execute(store=StubStore(), crawler=StubCrawler(), ai=ai))

    assert "stage=keyword_planning" in caplog.text
    assert "stage=report_analysis" in caplog.text
    assert ai.responses == []
    assert '"keywords":["通勤妆","敏感肌","底妆实测","妆前打底"]' in caplog.text
    assert '"categoryName": "高压通勤者"' in caplog.text


def test_fast_report_sections_finish_before_similar_accounts_ai_calls():
    """画像/合规/爆款先完成；相似博主千问被堵住时不应卡住前三段进度。"""

    async def scenario():
        release_similar = asyncio.Event()

        class IncrementalAI(StubAI):
            async def chat_completion(self, **kwargs):
                prompt = kwargs["messages"][0]["content"]
                is_keyword_plan = (
                    "规划所有平台共用的 3–5 个检索短词" in prompt
                    or "生成 3–5 个平台共用检索短词" in prompt
                    or "生成恰好 4 个平台共用检索短词" in prompt
                    or "中文社交媒体检索词规划员" in prompt
                )
                is_fast_section = (
                    "targetUserProfile 分块" in prompt
                    or "complianceRules 分块" in prompt
                    or "hotContents 分块" in prompt
                    or "上一次 targetUserProfile" in prompt
                    or "上一次 complianceRules" in prompt
                    or "上一次 hotContents" in prompt
                )
                if not is_keyword_plan and not is_fast_section:
                    await release_similar.wait()
                return await super().chat_completion(**kwargs)

        store = StubStore(platforms=["小红书"])
        task = asyncio.create_task(
            _execute(store=store, crawler=StubCrawler(), ai=IncrementalAI())
        )

        for _ in range(800):
            if not store.result_payloads:
                await asyncio.sleep(0.01)
                continue
            snapshot = store.result_payloads[-1]
            completed = set(snapshot.get("reportSectionsCompleted") or [])
            if completed >= {"complianceRules", "targetUserProfile", "hotContents"}:
                break
            await asyncio.sleep(0.01)
        else:
            release_similar.set()
            with pytest.raises(Exception):
                await asyncio.wait_for(task, timeout=2)
            raise AssertionError("fast sections did not complete before similarAccounts")

        snapshot = store.result_payloads[-1]
        assert task.done() is False
        assert "similarAccounts" not in (snapshot.get("reportSectionsCompleted") or [])
        assert set(snapshot["reportSectionsCompleted"]) == {
            "complianceRules",
            "targetUserProfile",
            "hotContents",
        }

        release_similar.set()
        await asyncio.wait_for(task, timeout=10)
        final = store.result_payloads[-1]
        assert "similarAccounts" in (final.get("reportSectionsCompleted") or [])

    asyncio.run(scenario())


def test_report_no_longer_persists_removed_sections():
    report = _report_payload(platforms=["小红书"])
    store = StubStore(platforms=["小红书"])

    result = asyncio.run(
        _execute(store=store, crawler=StubCrawler(), ai=StubAI(report=report))
    )

    assert result["reportVersion"] == 1
    persisted = store.replacements[0][2]
    assert len(persisted["targetUserProfile"]["categories"]) == 3
    assert "contentStrategy" not in persisted
    assert "topBloggerDetails" not in persisted


def test_profile_prompt_uses_scenario_and_payment_driven_template():
    ai = StubAI(report=_report_payload(platforms=["小红书"]))

    asyncio.run(
        _execute(
            store=StubStore(platforms=["小红书"]),
            crawler=StubCrawler(),
            ai=ai,
        )
    )

    profile_prompt = next(
        prompt for prompt in ai.messages if "targetUserProfile 分块" in prompt
    )
    assert "购买场景、需求状态或决策逻辑" in profile_prompt
    assert "输出3—5类最具有商业价值的核心目标用户" in profile_prompt
    assert "specificProfile" in profile_prompt
    assert "150–250" in profile_prompt
    assert "priorityRanking" in profile_prompt
    assert "positioningReminder" in profile_prompt
    profile_input = json.loads(profile_prompt.split("输入：", 1)[1])
    assert set(profile_input) == {"accountContext"}
    assert profile_input["accountContext"]["account"]["industry"] == "美妆"
    assert profile_input["accountContext"]["knowledgeContext"] == "产品: 底妆"
    assert "evidence" not in profile_input
    assert "sourceMeta" not in profile_input
    assert not any("contentStrategy 分块" in prompt for prompt in ai.messages)


def test_compliance_prompt_uses_industry_categories_and_preserves_output_contract():
    ai = StubAI(report=_report_payload(platforms=["小红书"]))

    asyncio.run(
        _execute(
            store=StubStore(platforms=["小红书"]),
            crawler=StubCrawler(),
            ai=ai,
        )
    )

    prompt = next(
        item for item in ai.messages if "complianceRules 分块" in item
    )
    assert "广告法极限词" in prompt
    assert "医疗功效词" in prompt
    assert "金融承诺词" in prompt
    assert "平台禁词" in prompt
    assert "行业敏感词清单" in prompt
    assert "不能把爬取结果当成敏感词库的唯一来源" in prompt
    assert "可在文案中直接检索的具体词或短语" in prompt
    assert "每个适用类别尽量给出 3–8 个" in prompt
    assert "全部 complianceRules 必须控制在 1–20 项" in prompt
    assert "suggestion 必须是字符串" in prompt
    assert "不得输出数组" in prompt
    assert "不输出账号信息、风险数量统计或合规建议等额外字段" in prompt
    assert '"riskLevel":"high"' in prompt
    assert '"expression":"风险表达"' in prompt


def test_runs_each_platform_creator_then_keyword_and_tracks_stages():
    store = StubStore()
    crawler = StubCrawler()
    result = asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))

    _assert_creator_then_keyword(crawler, ["xhs", "dy"])
    stage_transitions = []
    for _, stage in store.progress:
        if not stage_transitions or stage_transitions[-1] != stage:
            stage_transitions.append(stage)
    assert stage_transitions[:3] == [
        "context_loading",
        "keyword_planning",
        "creator_crawling",
    ]
    assert "keyword_crawling" in stage_transitions
    assert stage_transitions[-3:] == [
        "evidence_normalization",
        "report_analysis",
        "report_persistence",
    ]
    assert [progress for progress, _ in store.progress] == sorted(progress for progress, _ in store.progress)
    assert result["reportVersion"] == 1
    assert len(store.replacements) == 1

    payload = store.replacements[0][2]
    assert set(payload) == {
        "similarAccounts",
        "complianceRules",
        "targetUserProfile",
        "hotContents",
        "sourceMeta",
        "competitors",
        "prohibitedWords",
        "targetUsers",
        "hotContent",
    }
    compatibility_keys = (
        "competitors",
        "prohibitedWords",
        "targetUsers",
        "hotContent",
    )
    assert all(payload[key] for key in compatibility_keys)
    assert "topBloggerDetails" not in payload
    assert "contentStrategy" not in payload
    assert "topBloggers" not in payload
    assert payload["sourceMeta"]["generatedAt"].endswith(("Z", "+00:00"))
    assert len(payload["sourceMeta"]["keywords"]) == 5
    assert set(payload["sourceMeta"]["keywords"]) == {
        "通勤妆容",
        "敏感肌底妆",
        "底妆实测",
        "妆前打底",
        "底妆测评",
    }
    assert "keywordPack" not in payload["sourceMeta"]


def test_supported_platforms_crawl_concurrently_while_each_platform_stays_sequential():
    async def scenario():
        creator_started = {
            "xhs": asyncio.Event(),
            "dy": asyncio.Event(),
        }
        creator_release = {
            "xhs": asyncio.Event(),
            "dy": asyncio.Event(),
        }
        keyword_started = {
            "xhs": asyncio.Event(),
            "dy": asyncio.Event(),
        }

        class ParallelCrawler(StubCrawler):
            async def crawl_by_creator(self, *, creator_url, **options):
                platform = "xhs" if "xiaohongshu" in creator_url else "dy"
                creator_started[platform].set()
                await creator_release[platform].wait()
                return await super().crawl_by_creator(
                    creator_url=creator_url,
                    **options,
                )

            async def crawl_by_keyword(self, *, keywords, platform, **options):
                keyword_started[platform].set()
                return await super().crawl_by_keyword(
                    keywords=keywords,
                    platform=platform,
                    **options,
                )

        task = asyncio.create_task(
            _execute(store=StubStore(), crawler=ParallelCrawler(), ai=StubAI())
        )

        await asyncio.wait_for(
            asyncio.gather(
                creator_started["xhs"].wait(),
                creator_started["dy"].wait(),
            ),
            timeout=1,
        )
        assert keyword_started["xhs"].is_set() is False
        assert keyword_started["dy"].is_set() is False

        creator_release["xhs"].set()
        await asyncio.wait_for(keyword_started["xhs"].wait(), timeout=1)
        assert keyword_started["dy"].is_set() is False

        creator_release["dy"].set()
        await asyncio.wait_for(task, timeout=1)
        assert keyword_started["dy"].is_set() is True

    asyncio.run(scenario())


def test_mediaspider_keywords_run_concurrently_with_distinct_cookies():
    async def scenario():
        release = asyncio.Event()
        started: dict[str, str] = {}

        class ParallelKeywordCrawler(StubCrawler):
            async def crawl_by_keyword(self, *, keywords, platform, **options):
                assert platform == "xhs"
                assert len(keywords) == 1
                cookie = options["cookies"]
                started[cookie] = keywords[0]
                if len(started) == 5:
                    release.set()
                await asyncio.wait_for(release.wait(), timeout=1)
                return CrawlResult(
                    platform=platform,
                    crawl_type="search",
                    keywords=list(keywords),
                    contents=[
                        {
                            "content_id": f"post-{keywords[0]}",
                            "title": keywords[0],
                        }
                    ],
                    content_count=1,
                )

        cookie_pool = WorkflowCookiePool(
            {
                "xhs": ("cookie-a", "cookie-b", "cookie-c", "cookie-d", "cookie-e"),
                "dy": (),
                "ks": (),
            },
            RoundRobinCursor(),
        )
        store = StubStore(platforms=["小红书"])
        ai = StubAI(report=_report_payload(platforms=["小红书"]))
        await _execute(
            store=store,
            crawler=ParallelKeywordCrawler(),
            ai=ai,
            cookie_pool_loader=lambda: cookie_pool,
        )

        assert set(started) == {"cookie-a", "cookie-b", "cookie-c", "cookie-d", "cookie-e"}
        assert set(started.values()) == {"通勤妆", "敏感肌", "底妆实测", "妆前打底", "底妆测评"}
        evidence = _report_evidence_from_prompt(
            next(
                prompt
                for prompt in ai.messages
                if "hotContents 分块" in prompt
            )
        )
        # 账号定位锚点会过滤无关词；至少保留贴合产品服务的检索结果
        assert "底妆实测" in {
            item["source_keyword"]
            for item in evidence["industryEvidence"]["hotContents"]
        }
        assert set(started.values()) >= {
            item["source_keyword"]
            for item in evidence["industryEvidence"]["hotContents"]
        }
    asyncio.run(scenario())


def test_parallel_keyword_merge_preserves_richer_duplicate_author_fields():
    merged = merge_keyword_results(
        platform="xhs",
        keywords=["关键词一", "关键词二"],
        results=[
            CrawlResult(
                platform="xhs",
                crawl_type="search",
                keywords=["关键词一"],
                contents=[
                    {
                        "note_id": "same-note",
                        "user_id": "same-user",
                        "avatar": "",
                    }
                ],
                creators=[
                    {
                        "creator_hash": "same-creator",
                        "avatar": "",
                    }
                ],
            ),
            CrawlResult(
                platform="xhs",
                crawl_type="search",
                keywords=["关键词二"],
                contents=[
                    {
                        "note_id": "same-note",
                        "user_id": "same-user",
                        "avatar": "https://avatar.example/content.png",
                    }
                ],
                creators=[
                    {
                        "creator_hash": "same-creator",
                        "avatar": "https://avatar.example/creator.png",
                    }
                ],
            ),
        ],
    )

    assert merged.contents[0]["avatar"] == "https://avatar.example/content.png"
    assert merged.creators[0]["avatar"] == "https://avatar.example/creator.png"


def test_workflow_caps_each_platform_keyword_crawl_at_report_limit():
    store = StubStore(platforms=["小红书"])
    crawler = StubCrawler()

    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["小红书"])),
            settings=StubSettings(
                max_notes_count=30,
                report_max_notes_per_keyword=2,
            ),
        )
    )

    keyword_opts = [options for mode, _, options in crawler.calls if mode == "keyword"]
    assert keyword_opts
    assert keyword_opts[0]["max_notes_count"] == 2


def test_workflow_disables_comment_crawling_and_removes_unexpected_comments_from_ai():
    comment_text = "不应进入提示词的评论"

    class UnexpectedCommentCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            return CrawlResult(
                platform="xhs",
                crawl_type="creator",
                creators=[{"user_id": "owner"}],
                contents=[{"note_id": "own-note", "user_id": "owner"}],
                comments=[{"note_id": "own-note", "content": comment_text}],
                comment_count=1,
            )

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            return CrawlResult(
                platform="xhs",
                crawl_type="search",
                contents=[
                    _with_relatedness(
                        {"note_id": "industry-note", "user_id": "competitor"},
                        keywords,
                    )
                ],
                comments=[{"note_id": "industry-note", "content": comment_text}],
                comment_count=1,
            )

    crawler = UnexpectedCommentCrawler()
    ai = StubAI(report=_report_payload(platforms=["小红书"]))
    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.xiaohongshu.com/user/profile/owner"},
    )

    asyncio.run(_execute(store=store, crawler=crawler, ai=ai))

    assert all(call[2].get("enable_comments") is not True for call in crawler.calls)
    assert all(call[2].get("enable_sub_comments") is not True for call in crawler.calls)
    assert all(comment_text not in message for message in ai.messages)
    evidence = _hot_contents_evidence_from_ai(ai)
    assert evidence["currentAccountEvidence"]["comments"] == []
    assert evidence["industryEvidence"]["comments"] == []


def test_workflow_explicit_comment_reference_preserves_existing_comment_evidence():
    comment_text = "开启后保留这条聚合评论证据"

    class CommentCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            return CrawlResult(
                platform="xhs",
                crawl_type="creator",
                creators=[{"user_id": "owner"}],
            )

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            return CrawlResult(
                platform="xhs",
                crawl_type="search",
                contents=[
                    _with_relatedness(
                        {"note_id": "industry-note", "user_id": "competitor"},
                        keywords,
                    )
                ],
                comments=[{"note_id": "industry-note", "content": comment_text}],
            )

    crawler = CommentCrawler()
    ai = StubAI(report=_report_payload(platforms=["小红书"]))
    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.xiaohongshu.com/user/profile/owner"},
        reference_comments=True,
    )

    asyncio.run(_execute(store=store, crawler=crawler, ai=ai))

    first_keyword = next(options for mode, _, options in crawler.calls if mode == "keyword")
    assert first_keyword.get("enable_comments") is True
    assert any(comment_text in message for message in ai.messages)


def test_partial_platform_failure_degrades_and_sanitizes_summary():
    store = StubStore()
    result = asyncio.run(_execute(store=store, crawler=StubCrawler({"xhs"}), ai=StubAI()))

    failed = store.replacements[0][2]["sourceMeta"]["failedPlatforms"]
    serialized = json.dumps({"result": result, "failed": failed}, ensure_ascii=False)
    assert any(item["platform"] == "小红书" for item in failed)
    assert "secret" not in serialized
    assert "Cookie" not in serialized
    assert "Authorization" not in serialized
    assert "?" not in serialized


@pytest.mark.parametrize("partial_count, should_generate", [(9, False), (10, True)])
def test_blocked_partial_keyword_result_requires_at_least_ten_contents(
    partial_count,
    should_generate,
):
    class PartiallyBlockedCrawler(StubCrawler):
        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            contents = [
                _with_relatedness(
                    {
                        "note_id": f"partial-{index}",
                        "user_id": f"creator-{index}",
                        "title": f"已采集内容 {index}",
                    },
                    keywords,
                )
                for index in range(partial_count)
            ]
            raise CrawlerExecutionError(
                platform,
                RuntimeError(f"blocked Cookie={options['cookies']}"),
                CrawlResult(
                    platform=platform,
                    crawl_type="search",
                    keywords=list(keywords),
                    contents=contents,
                    content_count=partial_count,
                ),
                failure=CrawlerFailure(
                    code="platform_blocked",
                    message="不应透传",
                    suggestion="不应透传",
                ),
            )

    store = StubStore(platforms=["小红书"], links={"小红书": ""})
    crawler = PartiallyBlockedCrawler()

    if should_generate:
        ai = StubAI(report=_report_payload(platforms=["小红书"]))
        asyncio.run(_execute(store=store, crawler=crawler, ai=ai))
        evidence = _report_evidence_from_prompt(next(
            prompt for prompt in ai.messages
            if "hotContents 分块" in prompt
        ))
        assert len(evidence["industryEvidence"]["hotContents"]) >= 8
        assert store.replacements
        source_meta = store.replacements[0][2]["sourceMeta"]
        assert source_meta["sampleCount"] == partial_count
        assert source_meta["failedPlatforms"] == [
            {"platform": "小红书", "mode": "keyword", "reason": "平台触发访问验证，暂时无法采集"}
        ]
        summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
        assert summary["status"] == "partial"
        assert summary["contentCount"] == partial_count
        assert summary["failureCode"] == "platform_blocked"
    else:
        with pytest.raises(ValueError, match="所有支持平台采集失败"):
            asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))
        assert store.replacements == []


def test_blocked_partial_keyword_result_below_ten_is_excluded_when_other_platform_succeeds():
    class MixedCrawler(StubCrawler):
        async def crawl_by_keyword(self, *, keywords, platform, **options):
            if platform != "xhs":
                return await super().crawl_by_keyword(
                    keywords=keywords,
                    platform=platform,
                    **options,
                )
            self.calls.append(("keyword", platform, options))
            contents = [
                {
                    "note_id": f"discarded-partial-{index}",
                    "user_id": f"creator-{index}",
                    "title": f"不足门槛内容 {index}",
                }
                for index in range(9)
            ]
            raise CrawlerExecutionError(
                platform,
                RuntimeError(f"blocked Cookie={options['cookies']}"),
                CrawlResult(
                    platform=platform,
                    crawl_type="search",
                    keywords=list(keywords),
                    contents=contents,
                    content_count=len(contents),
                ),
                failure=CrawlerFailure(
                    code="platform_blocked",
                    message="不应透传",
                    suggestion="不应透传",
                ),
            )

    store = StubStore(
        platforms=["小红书", "抖音"],
        links={"小红书": "", "抖音": ""},
    )
    ai = StubAI(report=_report_payload(platforms=["小红书", "抖音"]))

    asyncio.run(_execute(store=store, crawler=MixedCrawler(), ai=ai))

    evidence = _hot_contents_evidence_from_ai(ai)
    content_ids = [
        item["content_id"] for item in evidence["industryEvidence"]["hotContents"]
    ]
    assert "post-dy" in content_ids
    assert all(str(item).startswith("post-dy") for item in content_ids)
    assert all("discarded-partial" not in message for message in ai.messages)
    assert store.replacements[0][2]["sourceMeta"]["sampleCount"] >= 8


def test_hot_content_report_persists_eight_liked_references_and_candidate_pool():
    class MixedMediaCrawler(StubCrawler):
        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            contents = []
            for keyword_index, keyword in enumerate(keywords or ["样本"]):
                contents.extend(
                    [
                        {
                            "note_id": f"video-{keyword_index}-{index}",
                            "type": "video",
                            "title": f"视频内容 {keyword} {index}",
                            "liked_count": 1000 - keyword_index * 20 - index,
                            "source_keyword": keyword,
                        }
                        for index in range(8)
                    ]
                    + [
                        {
                            "note_id": f"image-{keyword_index}-{index}",
                            "type": "normal",
                            "title": f"图文内容 {keyword} {index}",
                            "liked_count": 100 - keyword_index * 20 - index,
                            "source_keyword": keyword,
                        }
                        for index in range(8)
                    ]
                )
            return CrawlResult(
                platform=platform,
                crawl_type="search",
                keywords=list(keywords),
                contents=contents,
                content_count=len(contents),
            )

    store = StubStore(platforms=["小红书"], links={"小红书": ""})
    store.context["account"]["productService"] = "通勤底妆"
    store.context["account"]["purpose"] = "获客转化"
    store.context["account"]["conversionGoal"] = "咨询留资"
    ai = StubAI(report=_report_payload(platforms=["小红书"]))

    asyncio.run(_execute(store=store, crawler=MixedMediaCrawler(), ai=ai))

    persisted = store.replacements[0][2]["hotContents"]
    assert len(persisted) == 8
    assert all(item["contentType"] == "video" for item in persisted)
    pool = store.replacements[0][2]["sourceMeta"]["hotContentsCandidatePool"]
    # 强相关过滤后池可能收窄；展示仍应凑满 8（不够会翻页补货）
    assert len(pool) >= 8
    assert len(persisted) == 8

    hot_prompt = next(
        prompt
        for prompt in ai.messages
        if "本次只生成账号报告的 hotContents 分块" in prompt
    )
    candidates = _report_evidence_from_prompt(hot_prompt)["industryEvidence"][
        "hotContents"
    ]
    assert len(candidates) == 8
    assert all(item["content_type"] == "video" for item in candidates)


def test_workflow_persists_platform_progress_and_actionable_failures():
    store = StubStore(platforms=["小红书", "抖音"])
    crawler = ClassifiedCrawler(
        failures={
            ("keyword", "dy"): CrawlerFailure(
                code="credentials_expired",
                message="登录凭证失效或未生效",
                suggestion="更新抖音 Cookie 并重启服务",
            )
        }
    )

    asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))

    snapshot = store.result_payloads[-1]["crawlProgress"]
    douyin = next(
        item for item in snapshot["platformSummaries"] if item["platform"] == "dy"
    )
    assert douyin["status"] == "partial"
    assert douyin["failureCode"] == "credentials_expired"
    assert any(item["contentTitle"] == "样本" for item in snapshot["activities"])


def test_all_failed_error_lists_safe_platform_reasons():
    store = StubStore()
    crawler = ClassifiedCrawler(fail_all=True)

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))

    message = str(exc_info.value)
    assert "小红书：登录凭证失效或未生效" in message
    assert "抖音：登录凭证失效或未生效" in message
    assert "Cookie" not in message
    assert store.replacements == []


@pytest.mark.parametrize(
    "creator_url",
    [
        "https://www.douyin.com/user/cross-platform-owner",
        "https://www.xiaohongshu.com/explore/not-a-profile",
        "",
    ],
)
def test_invalid_creator_url_variants_still_run_keyword_crawl(creator_url):
    store = StubStore(
        platforms=["小红书"],
        links={"小红书": creator_url},
    )
    crawler = StubCrawler()

    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["小红书"])),
        )
    )

    pairs = _call_pairs(crawler)
    assert any(mode == "keyword" and platform == "xhs" for mode, platform in pairs)
    summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "completed"
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"
    assert summary["noticeMessage"] == "当前账号主页链接无效，已跳过主页公开信息采集"
    assert store.replacements[0][2]["sourceMeta"]["failedPlatforms"] == []


def test_classified_invalid_creator_url_becomes_notice_and_keyword_continues():
    invalid = CrawlerFailure(
        code="creator_url_invalid",
        message="博主主页链接无效或账号不存在",
        suggestion="在账号档案填写真实完整主页链接",
    )
    store = StubStore(platforms=["抖音"])
    crawler = ClassifiedCrawler(failures={("creator", "dy"): invalid})

    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["抖音"])),
        )
    )

    pairs = _call_pairs(crawler)
    assert ("creator", "dy") in pairs
    assert ("keyword", "dy") in pairs
    assert pairs[0] == ("creator", "dy")
    summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "completed"
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"
    assert store.replacements[0][2]["sourceMeta"]["failedPlatforms"] == []


def test_unclassified_exception_persists_generic_crawler_failure_code():
    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.xiaohongshu.com/user/profile/aaaaaaaaaaaaaaaaaaaaaaaa"},
    )
    crawler = StubCrawler({("keyword", "xhs")})

    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["小红书"])),
        )
    )

    summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "partial"
    assert summary["failureCode"] == "crawler_failed"
    assert "secret" not in json.dumps(summary, ensure_ascii=False).lower()


def test_all_failed_summary_uses_latest_keyword_reason_per_platform():
    creator_reason = "浏览器操作超时"
    keyword_reason = "登录凭证失效或未生效"
    crawler = ClassifiedCrawler(
        failures={
            ("creator", "xhs"): CrawlerFailure(
                code="browser_timeout",
                message=creator_reason,
                suggestion="稍后重试",
            ),
            ("keyword", "xhs"): CrawlerFailure(
                code="credentials_expired",
                message=keyword_reason,
                suggestion="更新平台凭证",
            ),
        }
    )
    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.xiaohongshu.com/user/profile/owner"},
    )

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))

    message = str(exc_info.value)
    assert f"小红书：{keyword_reason}" in message
    assert creator_reason not in message
    summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["failureCode"] == "credentials_expired"


def test_all_supported_crawls_fail_and_old_report_is_not_replaced():
    store = StubStore()
    with pytest.raises(ValueError, match="采集失败"):
        asyncio.run(_execute(store=store, crawler=StubCrawler({"xhs", "dy"}), ai=StubAI()))
    assert store.replacements == []


def test_video_channel_only_generates_explicit_degraded_report():
    report = _report_payload(platforms=["视频号"], keywords=[], unsupported=["视频号"])
    store = StubStore(platforms=["视频号"], links={})
    crawler = StubCrawler()
    result = asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI(report=report, keyword=json.dumps(report))))

    assert crawler.calls == []
    assert result["reportVersion"] == 1
    assert store.replacements[0][2]["sourceMeta"]["unsupportedPlatforms"] == ["视频号"]


def test_invalid_ai_report_does_not_persist():
    store = StubStore()
    ai = StubAI()
    ai.section_overrides["complianceRules"] = '{"similarAccounts":[]}'
    with pytest.raises(Exception):
        asyncio.run(_execute(store=store, crawler=StubCrawler(), ai=ai))
    assert store.replacements == []


def test_reference_sections_fall_back_to_deterministic_evidence_when_ai_fails():
    class ReferenceCrawler(StubCrawler):
        async def crawl_by_keyword(self, *, keywords, platform, **options):
            id_field = {"xhs": "note_id", "dy": "aweme_id"}[platform]
            user_field = "user_id" if platform == "xhs" else "sec_user_id"
            return CrawlResult(
                platform=platform,
                crawl_type="search",
                contents=[
                    _with_relatedness(
                        {
                            id_field: f"hot-{platform}",
                            user_field: f"peer-{platform}",
                            "title": f"{platform} 行业样本",
                            "liked_count": 100,
                            "content_type": "image" if platform == "xhs" else "video",
                            "nickname": f"{platform} 竞品",
                            "profile_url": (
                                f"https://www.xiaohongshu.com/user/profile/peer-{platform}"
                                if platform == "xhs"
                                else f"https://www.douyin.com/user/peer-{platform}"
                            ),
                            "follower_count": 50_000,
                        },
                        keywords,
                    )
                ],
                creators=[
                    {
                        user_field: f"peer-{platform}",
                        "nickname": f"{platform} 竞品",
                        "profile_url": (
                            f"https://www.xiaohongshu.com/user/profile/peer-{platform}"
                            if platform == "xhs"
                            else f"https://www.douyin.com/user/peer-{platform}"
                        ),
                        "follower_count": 50_000,
                    }
                ],
            )

    ai = StubAI()
    ai.section_overrides["similarAccounts"] = "not-json"
    ai.section_overrides["hotContents"] = "not-json"
    store = StubStore()
    store.context["similarTargetFansWan"] = 10

    asyncio.run(_execute(store=store, crawler=ReferenceCrawler(), ai=ai))

    persisted = store.replacements[0][2]
    assert persisted["similarAccounts"] == []
    assert len(persisted["hotContents"]) == 2
    discovery = persisted["sourceMeta"]["referenceDiscovery"]
    assert discovery["similarAccounts"]["status"] == "unavailable"
    assert discovery["similarAccounts"]["mode"] == "positioning_keyword_user_search"
    assert discovery["hotContents"]["generatedWithoutAI"] is True


def test_invalid_report_section_is_retried_without_repeating_other_sections():
    class RetryOnceAI(StubAI):
        def __init__(self):
            super().__init__()
            self.section_calls = {}

        async def chat_completion(self, **kwargs):
            prompt = kwargs["messages"][0]["content"]
            if "社媒对标研究员" in prompt or "对标账号顾问" in prompt or (
                "推荐" in prompt and "相似博主" in prompt
            ):
                self.section_calls["similarAccounts"] = (
                    self.section_calls.get("similarAccounts", 0) + 1
                )
                return await super().chat_completion(**kwargs)
            for key in (
                "similarAccounts",
                "complianceRules",
                "targetUserProfile",
                "hotContents",
            ):
                if f"本次只生成账号报告的 {key} 分块" in prompt:
                    self.section_calls[key] = self.section_calls.get(key, 0) + 1
                    if key == "targetUserProfile" and self.section_calls[key] == 1:
                        self.messages.append(prompt)
                        return json.dumps(
                            {
                                "targetUserProfile": {
                                    "summary": "提升职场 AI 应用能力以增强职业竞争力",
                                    "coreNeeds": ["工作提效"],
                                    "contentPreferences": ["工作场景实操教学"],
                                    "purchaseConcerns": ["课程是否能解决具体问题"],
                                    "conversionTriggers": ["同龄人真实案例"],
                                }
                            },
                            ensure_ascii=False,
                        )
                    break
            return await super().chat_completion(**kwargs)

    ai = RetryOnceAI()
    store = StubStore()

    result = asyncio.run(_execute(store=store, crawler=StubCrawler(), ai=ai))

    assert result["reportVersion"] == 1
    assert ai.section_calls["complianceRules"] == 1
    assert ai.section_calls["targetUserProfile"] == 2
    assert ai.section_calls["hotContents"] == 1
    retry_prompt = next(
        prompt
        for prompt in ai.messages
        if "上一次 targetUserProfile 响应无法通过" in prompt
    )
    assert "从头重新生成该分块" in retry_prompt
    assert "不得再使用旧版 summary、coreNeeds" in retry_prompt
    assert "categories 必须包含 3–5 类" in retry_prompt
    assert len(store.replacements) == 1


def test_cookie_is_only_passed_to_crawler_not_persisted_context_or_progress():
    store = StubStore()
    crawler = StubCrawler()
    asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))

    assert all(call[2]["cookies"].endswith("-secret") for call in crawler.calls)
    persisted = json.dumps(
        {
            "context": store.context,
            "progress": store.progress,
            "resultPayloads": store.result_payloads,
            "report": store.replacements,
        },
        ensure_ascii=False,
    )
    assert "xhs-secret" not in persisted
    assert "dy-secret" not in persisted


def test_workflow_loads_cookie_file_once_and_rotates_expired_cookie():
    loads = 0

    def loader():
        nonlocal loads
        loads += 1
        return StubCookiePool({"xhs": ("expired", "valid")})

    class RetryCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            if options["cookies"] == "expired":
                raise CrawlerExecutionError(
                    "xhs",
                    RuntimeError("unsafe"),
                    CrawlResult(platform="xhs", crawl_type="creator"),
                    failure=CrawlerFailure(
                        code="credentials_expired",
                        message="凭证失效",
                        suggestion="更新凭证",
                    ),
                )
            return CrawlResult(
                platform="xhs",
                crawl_type="creator",
                creators=[{"id": "owner"}],
                creator_count=1,
            )

    store = StubStore(platforms=["小红书"])
    crawler = RetryCrawler()

    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["小红书"])),
            cookie_pool_loader=loader,
        )
    )

    assert loads >= 1
    assert loads <= 2
    report_creator_cookies = []
    for mode, _platform, options in crawler.calls:
        if mode == "keyword":
            break
        if mode == "creator":
            report_creator_cookies.append(options["cookies"])
    assert report_creator_cookies == [
        "expired",
        "valid",
    ]


def test_recoverable_timeout_rotates_cookie_candidates():
    class NonAuthenticationCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            raise CrawlerExecutionError(
                "xhs",
                RuntimeError("unsafe"),
                CrawlResult(platform="xhs", crawl_type="creator"),
                failure=CrawlerFailure(
                    code="browser_timeout",
                    message="浏览器操作超时",
                    suggestion="稍后重试",
                ),
            )

    store = StubStore(platforms=["小红书"])
    crawler = NonAuthenticationCrawler()

    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["小红书"])),
            cookie_pool_loader=lambda: StubCookiePool(
                {"xhs": ("first", "second")}
            ),
        )
    )

    report_creator_cookies = []
    for mode, _platform, options in crawler.calls:
        if mode == "keyword":
            break
        if mode == "creator":
            report_creator_cookies.append(options["cookies"])
    assert report_creator_cookies == ["first", "second"]


def test_scheduler_import_registers_account_report_workflow():
    assert WorkflowScheduler is not None
    assert "account_report" in WorkflowRegister.all_types()


def test_account_report_ai_context_excludes_internal_and_contact_fields():
    from app.services.account_report.generation.context import (
        build_account_report_ai_context,
    )

    context = build_account_report_ai_context(
        {
            "id": "acc-secret",
            "userId": "user-secret",
            "name": "测试账号",
            "description": "通勤底妆",
            "industry": "美妆",
            "productService": "粉底液",
            "platforms": ["小红书"],
            "accountLinks": {"小红书": "https://secret.example/profile"},
        },
        knowledge_enabled=True,
        knowledge_context=(
            "产品: 粉底液\n产品介绍: 适合通勤\n联系方式: 13800138000\n"
            "Logo: https://secret.example/logo.png"
        ),
    )

    serialized = json.dumps(context, ensure_ascii=False)
    assert context["account"]["name"] == "测试账号"
    assert "acc-secret" not in serialized
    assert "user-secret" not in serialized
    assert "secret.example" not in serialized
    assert "13800138000" not in serialized


def test_keyword_planning_prompt_excludes_account_name():
    from app.services.account_report.generation.prompts.report import (
        build_keyword_planning_prompt,
    )

    account_context = {
        "account": {
            "name": "小金买房",
            "description": "分享上海刚需购房和二手房交易经验",
            "industry": "房地产",
            "productService": "购房咨询",
            "targetCity": "上海",
        },
        "knowledgeEnabled": False,
        "knowledgeContext": "",
    }

    prompt = build_keyword_planning_prompt(account_context)

    assert "小金买房" not in prompt
    assert '"description": "分享上海刚需购房和二手房交易经验"' in prompt
    assert "不得使用账号名称" in prompt
    assert "禁止自由发挥" in prompt
    assert "对标博主" in prompt or "benchmarkSeed" in prompt
    assert "严肃" in prompt
    assert "王者荣耀陪玩" in prompt
    assert account_context["account"]["name"] == "小金买房"


def test_refine_planned_keywords_keeps_account_anchor_only():
    from app.services.account_report.generation.keywords import refine_planned_keywords

    refined = refine_planned_keywords(
        ["游戏陪玩", "电竞陪练", "王者陪玩", "LOL陪玩", "和平精英陪玩", "三角洲陪玩"],
        {
            "account": {
                "industry": "电竞陪玩",
                "productService": "王者荣耀陪玩",
                "description": "专注王者荣耀陪玩上分",
            }
        },
    )
    assert "王者陪玩" in refined
    assert "游戏陪玩" not in refined
    assert "电竞陪练" not in refined
    assert "LOL陪玩" not in refined
    assert "和平精英陪玩" not in refined
    assert "三角洲陪玩" not in refined
    assert len(refined) >= 3
    assert all("王者" in item or "王者荣耀" in item for item in refined)


def test_filter_hot_contents_keeps_titles_with_account_anchor():
    from app.services.account_report.domain.models import ContentEvidence
    from app.services.account_report.evidence.hot_contents import select_balanced_hot_contents

    candidates = [
        ContentEvidence(
            platform="dy",
            content_id="ok",
            content_type="video",
            title="王者荣耀国服陪玩上分",
        ),
        ContentEvidence(
            platform="dy",
            content_id="bad",
            content_type="video",
            title="接单渠道都有哪些？#无畏契约陪玩 #三角洲陪玩",
        ),
    ]
    selected = select_balanced_hot_contents(
        candidates,
        platforms=["抖音"],
        account_context={
            "account": {"productService": "王者荣耀陪玩", "description": "王者陪玩"}
        },
    )
    assert [item.content_id for item in selected] == ["ok"]


def test_store_account_report_context_contains_only_profile_knowledge_and_links():
    records = {
        WorkflowRecord: SimpleNamespace(
            id="wf-1",
            type="account_report",
            account_id="acc-1",
            user_id="user-1",
            input_payload={"referenceComments": True},
        ),
        AccountRecord: SimpleNamespace(
            id="acc-1",
            user_id="user-1",
            status="active",
            name="测试账号",
            description="定位",
            purpose="获客",
            account_type="企业号",
            industry="美妆",
            product_service="底妆",
            target_city="上海",
            target_audience="通勤女性",
            conversion_goal="留资",
            platform="小红书",
            platforms=["小红书"],
            account_links={"小红书": "https://www.xiaohongshu.com/user/profile/1"},
            knowledge_base_id="kb-1",
        ),
        KnowledgeBaseRecord: SimpleNamespace(
            id="kb-1",
            user_id="user-1",
            status="active",
            product_name="底妆",
            product_intro="适合通勤",
            brand_story="通勤女性品牌",
            price="199 元",
            logo_url="https://secret.example/logo.png",
            image_materials=["https://secret.example/material.png"],
            website_url="https://secret.example/website",
            contact_info="13800138000",
            enabled_fields={
                "productIntro": True,
                "brandStory": True,
                "price": True,
                "logoUrl": True,
                "imageMaterials": True,
                "websiteUrl": True,
                "contactInfo": True,
            },
        ),
    }

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, model, _identifier):
            return records.get(model)

    context = WorkflowStore(session_factory=Session).account_report_context("wf-1")
    serialized = json.dumps(context, ensure_ascii=False)
    assert set(context) == {
        "account",
        "knowledgeEnabled",
        "knowledgeContext",
        "accountLinks",
        "similarTargetFansWan",
        "benchmarkAccounts",
        "reportKeywords",
        "previousHotContents",
        "hotContentsCandidatePool",
        "hotContentsSearchPage",
        "referenceComments",
        "sectionKey",
    }
    assert context["benchmarkAccounts"] == {}
    assert context["similarTargetFansWan"] is None
    assert context["referenceComments"] is True
    assert context["sectionKey"] == ""
    assert context["knowledgeEnabled"] is True
    assert "适合通勤" in context["knowledgeContext"]
    assert "通勤女性品牌" in context["knowledgeContext"]
    assert "199 元" in context["knowledgeContext"]
    assert "secret.example" not in context["knowledgeContext"]
    assert "13800138000" not in context["knowledgeContext"]
    assert "cookie" not in serialized.lower()
    assert "secret" not in serialized.lower()


@pytest.mark.parametrize(
    "stored_value",
    [None, False, 1, "true"],
)
def test_store_account_report_context_defaults_invalid_comment_reference_to_false(
    stored_value,
):
    workflow = SimpleNamespace(
        id="wf-1",
        type="account_report",
        account_id="acc-1",
        user_id="user-1",
        input_payload={"referenceComments": stored_value},
    )
    account = SimpleNamespace(
        id="acc-1",
        user_id="user-1",
        status="active",
        name="测试账号",
        description="定位",
        purpose="获客",
        account_type="企业号",
        industry="美妆",
        product_service="底妆",
        target_city="上海",
        target_audience="通勤女性",
        conversion_goal="留资",
        platform="小红书",
        platforms=["小红书"],
        account_links={},
        knowledge_base_id=None,
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, model, _identifier):
            return workflow if model is WorkflowRecord else account

    context = WorkflowStore(session_factory=Session).account_report_context("wf-1")

    assert context["referenceComments"] is False


def test_platform_aliases_are_normalized_and_missing_cookie_never_calls_crawler():
    store = StubStore(
        platforms=["xhs", "douyin", "kuaishou"],
        links={
            "xhs": "https://www.xiaohongshu.com/user/profile/1",
            "douyin": "https://www.douyin.com/user/2",
            "kuaishou": "https://www.kuaishou.com/profile/3",
        },
    )
    crawler = StubCrawler()
    with pytest.raises(ValueError, match="采集失败"):
        asyncio.run(
            _execute(
                store=store,
                crawler=crawler,
                ai=StubAI(),
                cookie_pool_loader=lambda: StubCookiePool(
                    {"xhs": (), "dy": (), "ks": ()}
                ),
            )
        )
    assert crawler.calls == []
    assert store.replacements == []
    assert {
        item["failureCode"]
        for item in store.result_payloads[-1]["crawlProgress"]["platformSummaries"]
    } == {"credentials_missing"}


def test_empty_creator_result_is_invalid_but_zero_keyword_result_is_successful():
    class EmptyResultCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            return CrawlResult(platform="xhs", crawl_type="creator")

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            return CrawlResult(platform="xhs", crawl_type="search")

    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.xiaohongshu.com/user/profile/owner"},
    )
    asyncio.run(
        _execute(
            store=store,
            crawler=EmptyResultCrawler(),
            ai=StubAI(report=_report_payload(platforms=["小红书"])),
        )
    )

    summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["status"] == "completed"
    assert summary["failureCode"] is None
    assert summary["noticeCode"] == "creator_url_invalid"
    assert summary["contentCount"] == 0
    assert store.replacements[0][2]["sourceMeta"]["failedPlatforms"] == []
    assert store.replacements


def test_unknown_platform_mixed_with_supported_platform_is_rejected_before_crawling():
    store = StubStore(platforms=["小红书", "微博"])
    crawler = StubCrawler()
    with pytest.raises(ValueError, match="不支持的平台"):
        asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))
    assert crawler.calls == []
    assert store.replacements == []


def test_creator_url_platform_mismatch_skips_creator_and_keeps_keyword_success():
    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.douyin.com/user/2?token=must-not-leak"},
    )
    crawler = StubCrawler()
    asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))

    pairs = _call_pairs(crawler)
    assert any(mode == "keyword" and platform == "xhs" for mode, platform in pairs)
    assert store.replacements[0][2]["sourceMeta"]["failedPlatforms"] == []
    summary = store.result_payloads[-1]["crawlProgress"]["platformSummaries"][0]
    assert summary["noticeCode"] == "creator_url_invalid"
    failed = store.replacements[0][2]["sourceMeta"]["failedPlatforms"]
    assert "?" not in json.dumps(failed, ensure_ascii=False)
    assert "must-not-leak" not in json.dumps(failed, ensure_ascii=False)


def test_creator_content_author_and_planned_profile_id_both_exclude_own_account():
    class OwnerAwareCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            return CrawlResult(
                platform="xhs",
                crawl_type="creator",
                creator_url=creator_url,
                contents=[{"note_id": "own-home-note", "user_id": "owner-from-content", "nickname": "同名账号"}],
            )

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            return CrawlResult(
                platform="xhs",
                crawl_type="search",
                keywords=list(keywords),
                contents=[
                    _with_relatedness(
                        {"note_id": "self-content", "user_id": "owner-from-content", "nickname": "同名账号"},
                        keywords,
                    ),
                    _with_relatedness(
                        {"note_id": "profile-self", "user_id": "aaaaaaaaaaaaaaaaaaaaaaaa", "nickname": "不同名字"},
                        keywords,
                    ),
                    _with_relatedness(
                        {"note_id": "competitor", "user_id": "competitor-id", "nickname": "同名账号"},
                        keywords,
                    ),
                ],
            )

    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.xiaohongshu.com/user/profile/aaaaaaaaaaaaaaaaaaaaaaaa"},
    )
    ai = StubAI()
    asyncio.run(_execute(store=store, crawler=OwnerAwareCrawler(), ai=ai))

    evidence = _hot_contents_evidence_from_ai(ai)
    industry = evidence["industryEvidence"]
    candidate_ids = {
        item["creator_hash"]
        for item in industry["similarAccounts"]
    }
    hot_ids = {item["content_id"] for item in industry["hotContents"]}
    assert hot_ids == {"competitor"}
    assert {
        item["content_id"]
        for item in evidence["currentAccountEvidence"]["contents"]
    } == {"own-home-note"}
    assert anonymize_user_id("owner-from-content") not in candidate_ids
    assert anonymize_user_id("aaaaaaaaaaaaaaaaaaaaaaaa") not in candidate_ids
    assert anonymize_user_id("competitor-id") in candidate_ids


def test_valid_profile_id_excludes_owner_when_creator_crawl_fails_but_keyword_succeeds():
    class FailedCreatorCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "dy", options))
            raise RuntimeError(f"failed url={creator_url} Cookie={options['cookies']}")

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            return CrawlResult(
                platform="dy",
                crawl_type="search",
                keywords=list(keywords),
                contents=[
                    _with_relatedness(
                        {"aweme_id": "self-post", "sec_user_id": "MS4wLjABAAAA-owner", "nickname": "账号改名"},
                        keywords,
                    ),
                    _with_relatedness(
                        {"aweme_id": "other-post", "sec_user_id": "competitor", "nickname": "测试账号"},
                        keywords,
                    ),
                ],
            )

    store = StubStore(
        platforms=["抖音"],
        links={"抖音": "https://www.douyin.com/user/MS4wLjABAAAA-owner?token=must-not-leak"},
    )
    ai = StubAI(report=_report_payload(platforms=["抖音"]))
    asyncio.run(_execute(store=store, crawler=FailedCreatorCrawler(), ai=ai))

    evidence = _hot_contents_evidence_from_ai(ai)
    industry = evidence["industryEvidence"]
    candidate_ids = {
        item["creator_hash"]
        for item in industry["similarAccounts"]
    }
    assert anonymize_user_id("MS4wLjABAAAA-owner") not in candidate_ids
    assert anonymize_user_id("competitor") in candidate_ids
    assert {item["content_id"] for item in industry["hotContents"]} == {
        "other-post"
    }
    assert "must-not-leak" not in json.dumps(store.replacements, ensure_ascii=False)


@pytest.mark.parametrize(
    "unknown_xhs_url",
    ["", "https://xhslink.com/short-code", "https://www.xiaohongshu.com/explore/not-a-profile"],
)
def test_unknown_owner_platform_keeps_keyword_industry_evidence(unknown_xhs_url):
    class MixedOwnerCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            platform = "xhs" if "xiaohongshu" in creator_url or "xhslink" in creator_url else "dy"
            self.calls.append(("creator", platform, options))
            if platform == "xhs":
                raise RuntimeError("creator failed")
            return CrawlResult(
                platform="dy",
                crawl_type="creator",
                creators=[{"sec_user_id": "MS4wLjABAAAA-owner"}],
            )

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            id_field = "note_id" if platform == "xhs" else "aweme_id"
            author_field = "user_id" if platform == "xhs" else "sec_user_id"
            owner = "unknown-self" if platform == "xhs" else "MS4wLjABAAAA-owner"
            competitor = f"{platform}-competitor"
            return CrawlResult(
                platform=platform,
                crawl_type="search",
                keywords=list(keywords),
                contents=[
                    _with_relatedness(
                        {id_field: f"{platform}-self-post", author_field: owner},
                        keywords,
                    ),
                    _with_relatedness(
                        {id_field: f"{platform}-other-post", author_field: competitor},
                        keywords,
                    ),
                ],
                comments=[
                    {id_field: f"{platform}-other-post", "content": f"{platform} 用户反馈"}
                ],
            )

    store = StubStore(
        platforms=["小红书", "抖音"],
        links={
            "小红书": unknown_xhs_url,
            "抖音": "https://www.douyin.com/user/MS4wLjABAAAA-owner",
        },
        reference_comments=True,
    )
    ai = StubAI()
    asyncio.run(_execute(store=store, crawler=MixedOwnerCrawler(), ai=ai))

    evidence = _hot_contents_evidence_from_ai(ai)
    industry = evidence["industryEvidence"]
    candidates = [
        item
        for item in industry["similarAccounts"]
    ]
    assert candidates
    assert {item["platform"] for item in candidates} == {"xhs", "dy"}
    assert {item["creator_hash"] for item in candidates} == {
        anonymize_user_id("unknown-self"),
        anonymize_user_id("xhs-competitor"),
        anonymize_user_id("dy-competitor"),
    }
    assert {item["content_id"] for item in industry["hotContents"]} == {
        "xhs-self-post",
        "xhs-other-post",
        "dy-other-post",
    }
    assert {item["platform"] for item in industry["comments"]} == {"xhs", "dy"}


def test_creator_content_record_id_is_not_mistaken_for_a_trusted_owner_id():
    class UntrustedOwnerCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            return CrawlResult(
                platform="xhs",
                crawl_type="creator",
                creator_url=creator_url,
                contents=[{"note_id": "creator-note", "id": "content-record-id"}],
            )

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            return CrawlResult(
                platform="xhs",
                crawl_type="search",
                keywords=list(keywords),
                contents=[
                    _with_relatedness(
                        {"note_id": "hot-note", "user_id": "possible-owner-or-competitor"},
                        keywords,
                    )
                ],
            )

    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.xiaohongshu.com/user/profile/bbbbbbbbbbbbbbbbbbbbbbbb"},
    )
    ai = StubAI(report=_report_payload(platforms=["小红书"]))
    asyncio.run(_execute(store=store, crawler=UntrustedOwnerCrawler(), ai=ai))

    evidence = _hot_contents_evidence_from_ai(ai)
    industry = evidence["industryEvidence"]
    assert {item["content_id"] for item in industry["hotContents"]} == {
        "hot-note"
    }
    assert {
        item["content_id"]
        for item in evidence["currentAccountEvidence"]["contents"]
    } == {"creator-note"}
    candidate_hashes = {
        item["creator_hash"]
        for item in industry["similarAccounts"]
    }
    assert anonymize_user_id("content-record-id") not in candidate_hashes


def test_persistence_filters_ai_candidates_through_separate_evidence_allowlists():
    class CandidateCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            platform = "xhs" if "xiaohongshu" in creator_url else "dy"
            self.calls.append(("creator", platform, options))
            if "bench" in creator_url:
                creator = {
                    "nickname": "对标种子",
                    "profile_url": creator_url,
                    "fans_count": 50_000,
                }
                if platform == "dy":
                    creator["sec_user_id"] = "bench-seed"
                else:
                    creator["user_id"] = "bench-seed"
                return CrawlResult(
                    platform=platform,
                    crawl_type="creator",
                    creators=[creator],
                    contents=[
                        {"title": "通勤妆容测评", "content_id": "bench-1"},
                        {"title": "敏感肌底妆", "content_id": "bench-2"},
                    ],
                )
            if platform == "xhs":
                raise RuntimeError("owner unknown")
            return CrawlResult(
                platform="dy",
                crawl_type="creator",
                creators=[{"sec_user_id": "dy-owner"}],
            )

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            if platform == "xhs":
                return CrawlResult(
                    platform="xhs",
                    crawl_type="search",
                    contents=[
                        {
                            "note_id": "xhs-hot",
                            "user_id": "unknown-xhs-author",
                            "title": f"{(keywords or ['样本'])[0]}样本",
                            "source_keyword": (keywords or ["样本"])[0],
                            "nickname": "小红书竞品",
                            "profile_url": "https://www.xiaohongshu.com/user/profile/unknown-xhs-author",
                            "follower_count": 40_000,
                        }
                    ],
                    creators=[
                        {
                            "user_id": "unknown-xhs-author",
                            "nickname": "小红书竞品",
                            "profile_url": "https://www.xiaohongshu.com/user/profile/unknown-xhs-author",
                            "follower_count": 40_000,
                        }
                    ],
                )
            return CrawlResult(
                platform="dy",
                crawl_type="search",
                contents=[
                    {"aweme_id": "dy-self", "sec_user_id": "dy-owner"},
                    {
                        "aweme_id": "dy-other",
                        "sec_user_id": "dy-competitor",
                        "title": f"{(keywords or ['样本'])[0]}样本",
                        "source_keyword": (keywords or ["样本"])[0],
                        "nickname": "真实竞品名称",
                        "profile_url": "https://www.douyin.com/user/dy-competitor",
                        "follower_count": 45_000,
                    },
                ],
                creators=[
                    {"sec_user_id": "dy-owner", "nickname": "自己"},
                    {
                        "sec_user_id": "dy-competitor",
                        "nickname": "竞***名",
                        "display_name": "真实竞品名称",
                        "profile_url": "https://www.douyin.com/user/dy-competitor",
                        "avatar_url": "https://example.com/dy-competitor.jpg",
                        "fans_count": 12_345,
                        "works_count": 67,
                        "liked_count": 890_000,
                    },
                ],
            )

    unknown_hash = anonymize_user_id("unknown-xhs-author")
    owner_hash = anonymize_user_id("dy-owner")
    competitor_hash = anonymize_user_id("dy-competitor")
    report = _report_payload()
    report["similarAccounts"] = [
        {
            "platform": "小红书",
            "creatorHash": unknown_hash,
            "accountId": unknown_hash,
            "name": "未知",
            "similarityReason": "AI反推",
        },
        {
            "platform": "抖音",
            "creatorHash": owner_hash,
            "accountId": owner_hash,
            "name": "自己",
            "similarityReason": "错误自身",
        },
        {
            "platform": "微博",
            "creatorHash": competitor_hash,
            "accountId": competitor_hash,
            "name": "错平台",
            "similarityReason": "平台未知",
        },
        {
            "platform": "douyin",
            "creatorHash": competitor_hash,
            "accountId": competitor_hash,
            "name": "AI伪造名称",
            "profileUrl": "https://evil.example/user",
            "similarityReason": "证据允许",
        },
    ]
    store = StubStore(
        platforms=["小红书", "抖音"],
        links={
            "小红书": "https://www.xiaohongshu.com/explore/not-profile",
            "抖音": "https://www.douyin.com/user/MS4wLjABAAAATestSecUidValue12",
        },
    )
    store.context["similarTargetFansWan"] = 12
    asyncio.run(_execute(store=store, crawler=CandidateCrawler(), ai=StubAI(report=report)))

    persisted = store.replacements[0][2]
    # 相似账号走定位召回 + 粉丝群体筛选，不再采用 AI 报告里的伪造候选
    assert len(persisted["similarAccounts"]) >= 1
    assert all(
        str(item.get("profileUrl") or "").startswith("https://")
        for item in persisted["similarAccounts"]
    )
    assert "evil.example" not in json.dumps(persisted, ensure_ascii=False)


def test_verbatim_long_comment_in_ai_report_is_rejected_without_persistence():
    comment_text = "这款产品连续使用一周后皮肤明显更稳定而且上妆不再卡粉"

    class CommentCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            return CrawlResult(
                platform="xhs",
                crawl_type="creator",
                creators=[{"user_id": "owner"}],
            )

        async def crawl_by_keyword(self, *, keywords, platform, **options):
            self.calls.append(("keyword", platform, options))
            return CrawlResult(
                platform="xhs",
                crawl_type="search",
                contents=[
                    _with_relatedness(
                        {"note_id": "note-1", "user_id": "competitor"},
                        keywords,
                    )
                ],
                comments=[{"note_id": "note-1", "content": comment_text}],
            )

    report = _report_payload(platforms=["小红书"])
    report["targetUserProfile"]["categories"][0]["femaleProfile"]["description"] = comment_text
    store = StubStore(
        platforms=["小红书"],
        links={"小红书": "https://www.xiaohongshu.com/user/profile/owner"},
        reference_comments=True,
    )
    with pytest.raises(ValueError, match="不允许的逐字评论") as exc_info:
        asyncio.run(_execute(store=store, crawler=CommentCrawler(), ai=StubAI(report=report)))

    assert comment_text not in str(exc_info.value)
    assert store.replacements == []


def test_backend_overrides_ai_generated_at_timestamp():
    report = _report_payload()
    report["sourceMeta"]["generatedAt"] = "1999-01-01T00:00:00Z"
    store = StubStore()
    asyncio.run(_execute(store=store, crawler=StubCrawler(), ai=StubAI(report=report)))

    generated_at = store.replacements[0][2]["sourceMeta"]["generatedAt"]
    assert generated_at != "1999-01-01T00:00:00Z"
    assert generated_at.endswith(("Z", "+00:00"))


def test_current_stage_matches_each_blocked_crawler_operation():
    async def scenario():
        creator_started = asyncio.Event()
        creator_release = asyncio.Event()
        keyword_started = asyncio.Event()
        keyword_release = asyncio.Event()

        class BlockingCrawler(StubCrawler):
            async def crawl_by_creator(self, *, creator_url, **options):
                creator_started.set()
                await creator_release.wait()
                return await super().crawl_by_creator(creator_url=creator_url, **options)

            async def crawl_by_keyword(self, *, keywords, platform, **options):
                keyword_started.set()
                await keyword_release.wait()
                return await super().crawl_by_keyword(keywords=keywords, platform=platform, **options)

        store = StubStore(platforms=["小红书"])
        crawler = BlockingCrawler()
        task = asyncio.create_task(_execute(store=store, crawler=crawler, ai=StubAI()))

        await creator_started.wait()
        assert store.progress[-1][1] == "creator_crawling"
        creator_release.set()
        await keyword_started.wait()
        assert store.progress[-1][1] == "keyword_crawling"
        keyword_release.set()
        await task
        progress_values = [progress for progress, _ in store.progress]
        assert progress_values == sorted(progress_values)

    asyncio.run(scenario())
