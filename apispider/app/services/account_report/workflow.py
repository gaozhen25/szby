"""账号报告的数据采集、分块 AI 分析与原子持久化 workflow。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.mediaspider.cookie_pool import (
    load_cookie_pool,
    run_with_cookie_candidates,
)
from app.services.mediaspider.failure_catalog import public_crawler_failure
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerExecutionError,
    CrawlerFailure,
)
from app.services.mediaspider.platform_resolver import resolve_creator_platform
from app.services.mediaspider.service import MediaCrawlerService
from app.services.mediaspider.vendor.user_hash import anonymize_user_id
from app.services.tikhub_service import TikHubCrawlService
from app.services.tikhub_service.failure import classify_tikhub_failure
from app.services.workflow.workflows.base import BaseWorkflow, WorkflowRegister

from .ai_context import build_account_report_ai_context
from .crawl_options import account_report_runtime_options
from .crawl_progress import AccountReportCrawlProgressTracker, CrawlTarget
from .evidence import build_report_evidence
from .hot_content_selection import select_balanced_hot_contents
from .models import AccountReportPayload, HotContent, KeywordPlan, ReportEvidence, SourceMeta
from .workflow_types import ACCOUNT_REPORT_WORKFLOW_TYPE
from .owner_identity import parse_planned_owner_id
from .prompts import build_keyword_planning_prompt
from .reference_fallback import (
    deterministic_hot_contents,
    deterministic_similar_accounts,
)
from .report_sections import (
    REPORT_SECTION_SPECS,
    ReportSectionSpec,
    build_report_section_prompt,
    build_report_section_retry_prompt,
    get_report_section_spec,
    parse_report_section,
)

logger = get_logger(__name__)

_MIN_RECOVERABLE_PARTIAL_CONTENTS = 10


@dataclass(frozen=True)
class CrawlPlan:
    platform_name: str
    platform_code: str
    creator_url: str


@dataclass
class PlatformCrawlOutcome:
    current_account_results: list[CrawlResult]
    industry_results: list[CrawlResult]
    owner_hashes: set[str]
    failed_platforms: list[dict[str, str]]
    successful_crawls: int = 0


_PLATFORM_ALIASES = {
    "xhs": ("小红书", "xhs"),
    "小红书": ("小红书", "xhs"),
    "dy": ("抖音", "dy"),
    "douyin": ("抖音", "dy"),
    "抖音": ("抖音", "dy"),
    "ks": ("快手", "ks"),
    "kuaishou": ("快手", "ks"),
    "快手": ("快手", "ks"),
}
_VIDEO_CHANNEL_ALIASES = {"视频号", "wechat_channels", "channels"}
_JSON_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)


def _strict_keyword_plan(raw: Any) -> KeywordPlan:
    text = str(raw or "").strip()
    match = _JSON_FENCE.fullmatch(text)
    if match:
        text = match.group(1).strip()
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("检索词规划不是合法的完整 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("检索词规划顶层必须是 JSON 对象")
    return KeywordPlan.model_validate(value)


def _canonical_platform(value: Any) -> tuple[str, str] | None:
    return _PLATFORM_ALIASES.get(str(value or "").strip().lower())


def _creator_url(links: dict[str, Any], name: str, code: str) -> str:
    for key, value in links.items():
        canonical = _canonical_platform(key)
        if canonical == (name, code):
            return str(value or "").strip()
    return ""


def _plans(account: dict[str, Any], links: dict[str, Any]) -> tuple[list[CrawlPlan], list[str]]:
    raw_platforms = account.get("platforms") or [account.get("platform")]
    plans: list[CrawlPlan] = []
    unsupported: list[str] = []
    seen: set[str] = set()
    for value in raw_platforms:
        raw = str(value or "").strip()
        canonical = _canonical_platform(raw)
        if canonical is None:
            if raw.lower() not in _VIDEO_CHANNEL_ALIASES:
                raise ValueError("账号包含不支持的平台配置")
            if "视频号" not in unsupported:
                unsupported.append("视频号")
            continue
        name, code = canonical
        if code in seen:
            continue
        seen.add(code)
        plans.append(CrawlPlan(name, code, _creator_url(links, name, code)))
    return plans, unsupported


def _failed_platform(platform: str, mode: str, reason: str) -> dict[str, str]:
    """只接受内部固定摘要，绝不回显底层异常、URL、请求头或凭证。"""
    return {"platform": platform, "mode": mode, "reason": reason}


def _owner_identifiers(result: CrawlResult) -> set[str]:
    values: set[str] = set()
    for item in result.creators:
        for key in ("creator_hash", "author_id", "user_id", "sec_user_id", "uid", "id"):
            value = str(item.get(key) or "").strip()
            if value:
                values.add(value)
                break
    for item in result.contents:
        for key in ("creator_hash", "author_id", "user_id", "sec_user_id", "uid"):
            value = str(item.get(key) or "").strip()
            if value:
                values.add(value)
                break
    return values


def _owner_identifiers_from_plan(plan: CrawlPlan) -> set[str]:
    """仅从平台已校验主页解析稳定 ID，不使用易重名的展示名称。"""

    if not plan.creator_url:
        return set()
    try:
        if resolve_creator_platform(plan.creator_url) != plan.platform_code:
            return set()
        owner_id = parse_planned_owner_id(plan.platform_code, plan.creator_url)
    except Exception:
        return set()
    return {anonymize_user_id(owner_id)} if owner_id else set()


def _persistence_payload(report: AccountReportPayload) -> dict[str, Any]:
    payload = report.model_dump(mode="json", by_alias=True)
    payload["topBloggerDetails"] = payload.pop("topBloggers")
    payload.update(report.compatibility_summaries())
    return payload


def _candidate_key(platform: str, creator_hash: str) -> tuple[str, str] | None:
    canonical = _canonical_platform(platform)
    if canonical is None:
        return None
    return canonical[1], str(creator_hash or "").strip()


def _content_candidate_key(
    platform: str, content_id: str
) -> tuple[str, str] | None:
    canonical = _canonical_platform(platform)
    if canonical is None:
        return None
    normalized_content_id = str(content_id or "").strip()
    return (canonical[1], normalized_content_id) if normalized_content_id else None


def _filter_report_candidates(
    report: AccountReportPayload,
    evidence: ReportEvidence,
) -> AccountReportPayload:
    """AI 只能选择证据候选，不得从热门内容反推或编造账号。"""

    similar_allowlist = {
        key
        for item in evidence.industry.similar_accounts
        if (key := _candidate_key(item.platform, item.creator_hash)) is not None
    }
    top_allowlist = {
        key
        for item in evidence.industry.top_bloggers
        if (key := _candidate_key(item.platform, item.creator_hash)) is not None
    }
    hot_content_allowlist = {
        key
        for item in evidence.industry.hot_contents
        if (
            key := _content_candidate_key(item.platform, item.content_id)
        )
        is not None
    }
    return report.model_copy(
        update={
            "hot_contents": [
                item
                for item in report.hot_contents
                if _content_candidate_key(item.platform, item.content_id)
                in hot_content_allowlist
            ],
            "similar_accounts": [
                item
                for item in report.similar_accounts
                if _candidate_key(item.platform, item.creator_hash) in similar_allowlist
            ],
            "top_bloggers": [
                item
                for item in report.top_bloggers
                if _candidate_key(item.platform, item.creator_hash) in top_allowlist
            ],
        }
    )


def _merge_hot_content_urls(
    report: AccountReportPayload,
    evidence: ReportEvidence,
) -> AccountReportPayload:
    """AI 仅选择热门内容，公开链接和指标始终以已采集证据为准。"""

    trusted_contents = {
        key: item
        for item in evidence.industry.hot_contents
        if (key := _content_candidate_key(item.platform, item.content_id)) is not None
    }
    return report.model_copy(
        update={
            "hot_contents": [
                item.model_copy(
                    update={
                        "public_url": source.public_url if source else "",
                        "content_type": source.content_type if source else "unknown",
                        "metrics": _trusted_content_metrics(source),
                    }
                )
                for item in report.hot_contents
                if (source := trusted_contents.get(
                    _content_candidate_key(item.platform, item.content_id)
                )) is not None
            ]
        }
    )


def _trusted_content_metrics(source: Any) -> dict[str, int | float]:
    """生成统一的公开互动指标，禁止使用 AI 补造或遗漏的数值。"""

    return {
        "likedCount": source.liked_count,
        "collectedCount": source.collected_count,
        "commentCount": source.comment_count,
        "shareCount": source.share_count,
        "viewCount": source.view_count,
        "engagementScore": source.engagement_score,
        "hotScore": source.hot_score,
    }


def _merge_creator_display_data(
    report: AccountReportPayload,
    evidence: ReportEvidence,
) -> AccountReportPayload:
    """仅从已采集候选回填真实昵称和主页链接。"""

    similar_sources = {
        key: item
        for item in evidence.industry.similar_accounts
        if (key := _candidate_key(item.platform, item.creator_hash)) is not None
    }
    top_sources = {
        key: item
        for item in evidence.industry.top_bloggers
        if (key := _candidate_key(item.platform, item.creator_hash)) is not None
    }

    def merge(item, sources):
        source = sources.get(_candidate_key(item.platform, item.creator_hash))
        if source is None:
            return item
        updates = {
            "profile_url": source.profile_url,
            "avatar_url": source.avatar_url,
        }
        if source.display_name:
            updates["name"] = source.display_name
        return item.model_copy(update=updates)

    return report.model_copy(
        update={
            "similar_accounts": [
                merge(item, similar_sources) for item in report.similar_accounts
            ],
            "top_bloggers": [merge(item, top_sources) for item in report.top_bloggers],
        }
    )


def _normalized_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _iter_text_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_text_values(item)


def _reject_verbatim_comments(
    report: AccountReportPayload,
    evidence: ReportEvidence,
) -> None:
    _reject_verbatim_comment_values(
        report.model_dump(mode="json", by_alias=True),
        evidence,
    )


def _reject_verbatim_comment_values(value: Any, evidence: ReportEvidence) -> None:
    report_texts = [
        _normalized_text(value)
        for value in _iter_text_values(value)
    ]
    comments = [
        *evidence.current_account.comments,
        *evidence.industry.comments,
    ]
    for comment in comments:
        normalized_comment = _normalized_text(comment.text)
        if len(normalized_comment) < 8:
            continue
        if any(normalized_comment in value for value in report_texts):
            raise ValueError("账号报告包含不允许的逐字评论内容")


def _sanitize_report_section(key: str, value: Any, evidence: ReportEvidence) -> Any:
    """分块写入 workflow 前应用与最终报告相同的证据边界。"""

    if key == "similarAccounts":
        allowlist = {
            item_key
            for item in evidence.industry.similar_accounts
            if (item_key := _candidate_key(item.platform, item.creator_hash)) is not None
        }
        sources = {
            item_key: item
            for item in evidence.industry.similar_accounts
            if (item_key := _candidate_key(item.platform, item.creator_hash)) is not None
        }
        generated = {
            item_key: item
            for item in value
            if (item_key := _candidate_key(item.platform, item.creator_hash))
            in allowlist
        }
        sanitized = []
        for fallback in deterministic_similar_accounts(evidence):
            item_key = _candidate_key(fallback.platform, fallback.creator_hash)
            source = sources[item_key]
            item = generated.get(item_key, fallback)
            updates = {
                "profile_url": source.profile_url,
                "avatar_url": source.avatar_url,
            }
            if source.display_name:
                updates["name"] = source.display_name
            sanitized.append(item.model_copy(update=updates))
        value = sanitized
    elif key == "hotContents":
        sources = {
            item_key: item
            for item in evidence.industry.hot_contents
            if (item_key := _content_candidate_key(item.platform, item.content_id)) is not None
        }
        selected_sources = select_balanced_hot_contents(
            evidence.industry.hot_contents
        )
        generated = {
            item_key: item
            for item in value
            if (item_key := _content_candidate_key(item.platform, item.content_id))
            in sources
        }
        sanitized = []
        for source in selected_sources:
            item_key = _content_candidate_key(source.platform, source.content_id)
            item = generated.get(item_key)
            if item is None:
                type_label = "视频" if source.content_type == "video" else "图文"
                item = HotContent(
                    platform=source.platform,
                    contentId=source.content_id,
                    title=source.title or "未命名公开内容",
                    selectionReason=f"用于补充{type_label}内容形态参考",
                    metrics=_trusted_content_metrics(source),
                )
            sanitized.append(
                item.model_copy(
                    update={
                        "public_url": source.public_url,
                        "content_type": source.content_type,
                        "metrics": _trusted_content_metrics(source),
                    }
                )
            )
        value = sanitized
    elif key == "topBloggers":
        sources = {
            item_key: item
            for item in evidence.industry.top_bloggers
            if (item_key := _candidate_key(item.platform, item.creator_hash)) is not None
        }
        sanitized = []
        for item in value:
            item_key = _candidate_key(item.platform, item.creator_hash)
            if item_key not in sources:
                continue
            source = sources[item_key]
            updates = {
                "profile_url": source.profile_url,
                "avatar_url": source.avatar_url,
            }
            if source.display_name:
                updates["name"] = source.display_name
            sanitized.append(item.model_copy(update=updates))
        value = sanitized

    dumped = (
        [item.model_dump(mode="json", by_alias=True) for item in value]
        if isinstance(value, list)
        else value.model_dump(mode="json", by_alias=True)
    )
    _reject_verbatim_comment_values(dumped, evidence)
    return dumped


def _report_version(value: Any) -> int:
    if isinstance(value, dict):
        return int(value.get("reportVersion") or value.get("report_version") or 0)
    return int(getattr(value, "reportVersion", None) or getattr(value, "report_version", 0) or 0)


def _section_persistence_payload(
    section_key: str,
    value: Any,
    source_meta: dict[str, Any],
) -> dict[str, Any]:
    """构造单板块原子更新载荷，并同步对应的旧版可读摘要。"""

    payload: dict[str, Any] = {section_key: value, "sourceMeta": source_meta}
    if section_key == "similarAccounts":
        payload["competitors"] = "；".join(
            f"{item.get('name') or '未命名账号'}（{item.get('platform') or '未知平台'}）："
            f"{item.get('similarityReason') or '暂无相似原因'}"
            for item in value
        ) or "暂无足够的公开相似账号样本。"
    elif section_key == "complianceRules":
        risk_labels = {"high": "高", "medium": "中", "low": "低"}
        payload["prohibitedWords"] = "；".join(
            f"[{risk_labels.get(item.get('riskLevel'), '中')}] "
            f"{item.get('expression') or '风险表达'}：{item.get('reason') or '存在风险'}；"
            f"建议：{item.get('suggestion') or '请使用审慎表达'}"
            for item in value
        )
    elif section_key == "targetUserProfile":
        categories = list(value.get("categories") or [])
        ranking = dict(value.get("priorityRanking") or {})
        summary = "；".join(
            f"{item.get('categoryName') or '用户类别'}：{item.get('purchaseMotivation') or '暂无购买动机'}"
            for item in categories
        )
        priority_category = str(ranking.get("priorityCategory") or "").strip()
        if priority_category:
            summary += (
                f"。优先服务：{priority_category}，"
                f"{ranking.get('priorityReason') or '建议优先验证该用户类别'}"
            )
        payload["targetUsers"] = summary
    elif section_key == "hotContents":
        payload["hotContent"] = "；".join(
            f"{item.get('title') or '未命名内容'}（{item.get('platform') or '未知平台'}）："
            f"{item.get('selectionReason') or '高互动公开内容'}"
            for item in value
        ) or "暂无足够的公开爆款样本。"
    return payload


def _recoverable_partial_result(error: CrawlerExecutionError) -> CrawlResult | None:
    """风控中断时仅接纳实际保留了至少 10 条内容记录的部分结果。"""

    result = error._recoverable_result_copy()
    if len(result.contents) < _MIN_RECOVERABLE_PARTIAL_CONTENTS:
        return None
    return result


def _without_comments(result: CrawlResult) -> CrawlResult:
    """在 AI 证据边界移除意外返回的评论，不修改爬虫原始结果。"""

    return result.model_copy(update={"comments": [], "comment_count": 0})


@WorkflowRegister.register
class AccountReportWorkflow(BaseWorkflow):
    type = ACCOUNT_REPORT_WORKFLOW_TYPE
    section_key: str | None = None

    async def _complete(self, prompt: str, *, stage: str) -> str:
        result = await self.ai_service.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = str(result or "")
        logger.info(
            "account_report ai_response workflow_id=%s stage=%s response_length=%s response=%s",
            self.workflow_id,
            stage,
            len(content),
            content,
        )
        if not content.strip():
            raise ValueError("AI 服务未返回有效结果")
        return content

    async def execute(self) -> dict[str, Any]:
        self.store.update_progress(self.workflow_id, progress=5, current_stage="context_loading")
        context = self.store.account_report_context(self.workflow_id)
        reference_comments = context.get("referenceComments") is True
        requested_section_key = self.section_key or str(context.get("sectionKey") or "").strip()
        generation_specs = (
            (get_report_section_spec(requested_section_key),)
            if requested_section_key
            else REPORT_SECTION_SPECS
        )
        account = dict(context.get("account") or {})
        links = dict(context.get("accountLinks") or {})
        ai_context = build_account_report_ai_context(
            account,
            knowledge_enabled=bool(context.get("knowledgeEnabled")),
            knowledge_context=str(context.get("knowledgeContext") or ""),
        )
        plans, unsupported = _plans(account, links)
        if not plans and unsupported != ["视频号"]:
            raise ValueError("账号未配置可生成报告的平台")

        self.store.update_progress(self.workflow_id, progress=10, current_stage="keyword_planning")
        keywords: list[str] = []
        if plans:
            keywords = _strict_keyword_plan(
                await self._complete(
                    build_keyword_planning_prompt(ai_context),
                    stage="keyword_planning",
                )
            ).keywords

        runtime_settings = self.context.get("_settings") or settings
        injected_crawler = self.context.get("_crawler_service")
        legacy_cookie_pool_loader = self.context.get("_cookie_pool_loader")
        configured_legacy = (
            injected_crawler is None
            and getattr(runtime_settings, "social_retrieval_provider", "tikhub")
            == "legacy"
        )
        if configured_legacy:
            legacy_cookie_pool_loader = load_cookie_pool
        use_legacy_provider = legacy_cookie_pool_loader is not None and (
            injected_crawler is not None or configured_legacy
        )
        crawler = (
            injected_crawler
            or (MediaCrawlerService() if configured_legacy else TikHubCrawlService())
        )
        cookie_pool = (
            legacy_cookie_pool_loader()
            if use_legacy_provider
            else None
        )
        current_account_results: list[CrawlResult] = []
        industry_results: list[CrawlResult] = []
        owner_hashes: set[str] = set()
        failed_platforms: list[dict[str, str]] = []
        successful_crawls = 0
        tracker = AccountReportCrawlProgressTracker(
            self.workflow_id,
            self.store,
            [CrawlTarget(plan.platform_name, plan.platform_code) for plan in plans],
            track_comments=reference_comments,
        )

        runtime_options_by_platform = {
            plan.platform_code: account_report_runtime_options(
                runtime_settings,
                plan.platform_code,
                reference_comments=reference_comments,
            )
            for plan in plans
        }

        def enter_crawl_stage(stage: str, index: int, start: int) -> None:
            progress = start + (index * 25 // max(len(plans), 1))
            tracker.set_stage(progress=progress, current_stage=stage)

        def record_failure(
            plan: CrawlPlan,
            *,
            mode: str,
            failure: CrawlerFailure,
            compatible_reason: str | None = None,
        ) -> dict[str, str]:
            tracker.fail(plan.platform_code, mode=mode, failure=failure)
            summary = next(
                item
                for item in tracker.snapshot()["platformSummaries"]
                if item["platform"] == plan.platform_code
            )
            return _failed_platform(
                plan.platform_name,
                mode,
                compatible_reason
                or str(summary.get("failureMessage") or "平台采集失败"),
            )

        def record_notice(plan: CrawlPlan, *, mode: str) -> None:
            tracker.notice(
                plan.platform_code,
                mode=mode,
                code="creator_url_invalid",
            )

        def result_counts(result: CrawlResult) -> tuple[int, int, int]:
            return (
                max(result.content_count, len(result.contents)),
                max(result.creator_count, len(result.creators)),
                (
                    max(result.comment_count, len(result.comments))
                    if reference_comments
                    else 0
                ),
            )

        missing_credentials = public_crawler_failure("credentials_missing")
        generic_crawler_failure = public_crawler_failure("crawler_failed")

        async def crawl_platform(index: int, plan: CrawlPlan) -> PlatformCrawlOutcome:
            outcome = PlatformCrawlOutcome([], [], set(), [])
            enter_crawl_stage("creator_crawling", index, 15)
            # 让所有平台任务先进入采集阶段，再各自执行平台内的串行链路。
            await asyncio.sleep(0)
            runtime_options = runtime_options_by_platform[plan.platform_code]
            if use_legacy_provider and not cookie_pool.has_cookies(plan.platform_code):
                outcome.failed_platforms.append(
                    record_failure(
                        plan,
                        mode="configuration",
                        failure=missing_credentials,
                        compatible_reason="未配置平台凭证",
                    )
                )
                return outcome
            planned_owner_hashes = _owner_identifiers_from_plan(plan)
            outcome.owner_hashes.update(planned_owner_hashes)
            if plan.creator_url:
                if not planned_owner_hashes:
                    record_notice(plan, mode="creator")
                else:
                    try:
                        async def crawl_creator(cookie: str = ""):
                            if not use_legacy_provider:
                                return await crawler.crawl_by_creator(
                                    creator_url=plan.creator_url,
                                    on_progress=tracker.callback(
                                        plan.platform_name,
                                        "creator",
                                    ),
                                    max_notes_count=int(
                                        runtime_options["max_notes_count"]
                                    ),
                                    enable_comments=bool(
                                        runtime_options["enable_comments"]
                                    ),
                                    max_comments_count=int(
                                        runtime_options["max_comments_count"]
                                    ),
                                )
                            return await crawler.crawl_by_creator(
                                creator_url=plan.creator_url,
                                on_progress=tracker.callback(
                                    plan.platform_name,
                                    "creator",
                                ),
                                cookies=cookie,
                                **runtime_options,
                            )

                        creator_result = (
                            await run_with_cookie_candidates(
                                cookie_pool,
                                plan.platform_code,
                                crawl_creator,
                            )
                            if use_legacy_provider
                            else await crawl_creator()
                        )
                        content_count, creator_count, comment_count = result_counts(
                            creator_result
                        )
                        if content_count == 0 and creator_count == 0:
                            record_notice(plan, mode="creator")
                        else:
                            outcome.current_account_results.append(creator_result)
                            creator_identifiers = _owner_identifiers(creator_result)
                            outcome.owner_hashes.update(creator_identifiers)
                            tracker.complete(
                                plan.platform_code,
                                content_count=content_count,
                                creator_count=creator_count,
                                comment_count=comment_count,
                            )
                            outcome.successful_crawls += 1
                            numeric_owner_ids = [
                                str(item.get("numeric_user_id") or "")
                                for item in creator_result.creators
                                if str(item.get("numeric_user_id") or "").isdigit()
                            ]
                            if numeric_owner_ids:
                                runtime_options = {
                                    **runtime_options,
                                    "owner_user_ids": numeric_owner_ids,
                                }
                    except CrawlerExecutionError as exc:
                        if exc.failure.code == "creator_url_invalid":
                            record_notice(plan, mode="creator")
                        else:
                            partial_result = _recoverable_partial_result(exc)
                            if partial_result is not None:
                                outcome.current_account_results.append(partial_result)
                                outcome.owner_hashes.update(
                                    _owner_identifiers(partial_result)
                                )
                                content_count, creator_count, comment_count = (
                                    result_counts(partial_result)
                                )
                                tracker.complete(
                                    plan.platform_code,
                                    content_count=content_count,
                                    creator_count=creator_count,
                                    comment_count=comment_count,
                                )
                                outcome.successful_crawls += 1
                            outcome.failed_platforms.append(
                                record_failure(
                                    plan,
                                    mode="creator",
                                    failure=exc.failure,
                                )
                            )
                    except Exception:
                        outcome.failed_platforms.append(
                            record_failure(
                                plan,
                                mode="creator",
                                failure=generic_crawler_failure,
                                compatible_reason="账号主页采集失败",
                            )
                        )
            else:
                record_notice(plan, mode="creator")

            enter_crawl_stage("keyword_crawling", index, 40)
            try:
                async def crawl_keyword(cookie: str = ""):
                    return await crawler.crawl_by_keyword(
                        keywords=keywords,
                        platform=plan.platform_code,
                        on_progress=tracker.callback(
                            plan.platform_name,
                            "keyword",
                        ),
                        **({"cookies": cookie} if use_legacy_provider else {}),
                        **runtime_options,
                    )

                keyword_result = (
                    await run_with_cookie_candidates(
                        cookie_pool,
                        plan.platform_code,
                        crawl_keyword,
                    )
                    if use_legacy_provider
                    else await crawl_keyword()
                )
                outcome.industry_results.append(keyword_result)
                content_count, creator_count, comment_count = result_counts(keyword_result)
                tracker.complete(
                    plan.platform_code,
                    content_count=content_count,
                    creator_count=creator_count,
                    comment_count=comment_count,
                )
                outcome.successful_crawls += 1
            except CrawlerExecutionError as exc:
                partial_result = _recoverable_partial_result(exc)
                if partial_result is not None:
                    outcome.industry_results.append(partial_result)
                    content_count, creator_count, comment_count = result_counts(
                        partial_result
                    )
                    tracker.complete(
                        plan.platform_code,
                        content_count=content_count,
                        creator_count=creator_count,
                        comment_count=comment_count,
                    )
                    outcome.successful_crawls += 1
                outcome.failed_platforms.append(
                    record_failure(plan, mode="keyword", failure=exc.failure)
                )
            except Exception as exc:
                logger.exception(
                    "账号报告关键词采集失败: workflow_id=%s platform=%s "
                    "cause=%s request_id=%s",
                    self.workflow_id,
                    plan.platform_code,
                    type(exc).__name__,
                    getattr(exc, "request_id", None),
                )
                outcome.failed_platforms.append(
                    record_failure(
                        plan,
                        mode="keyword",
                        failure=(
                            classify_tikhub_failure(exc)
                            or generic_crawler_failure
                        ),
                        compatible_reason="关键词采集失败",
                    )
                )
            return outcome

        platform_outcomes = await asyncio.gather(
            *(crawl_platform(index, plan) for index, plan in enumerate(plans))
        )
        for outcome in platform_outcomes:
            current_account_results.extend(outcome.current_account_results)
            industry_results.extend(outcome.industry_results)
            owner_hashes.update(outcome.owner_hashes)
            failed_platforms.extend(outcome.failed_platforms)
            successful_crawls += outcome.successful_crawls

        if plans and successful_crawls == 0:
            raise ValueError(tracker.failure_summary())

        self.store.update_progress(self.workflow_id, progress=70, current_stage="evidence_normalization")
        if not reference_comments:
            current_account_results = [
                _without_comments(result) for result in current_account_results
            ]
            industry_results = [_without_comments(result) for result in industry_results]
        evidence = build_report_evidence(
            current_account_results,
            industry_results,
            owner_hashes,
        )
        source_meta = SourceMeta.model_validate(
            {
                "platforms": [plan.platform_name for plan in plans] or ["视频号"],
                "keywords": keywords,
                "sampleCount": len(evidence.industry.hot_contents),
                "failedPlatforms": failed_platforms,
                "unsupportedPlatforms": unsupported,
                "generatedAt": datetime.now(UTC),
            }
        )

        source_meta_value = source_meta.model_dump(mode="json", by_alias=True)
        reference_operations = sorted(
            {
                operation
                for result in industry_results
                for operation in result.source_operations
            }
        )
        reference_warnings = sorted(
            {
                warning
                for result in industry_results
                for warning in result.discovery_warnings
            }
        )
        similar_count = len(evidence.industry.similar_accounts)
        hot_count = len(select_balanced_hot_contents(evidence.industry.hot_contents))
        source_meta_value["referenceDiscovery"] = {
            "similarAccounts": {
                "status": (
                    "complete" if similar_count >= 8 else "partial" if similar_count else "unavailable"
                ),
                "candidateCount": similar_count,
                "selectedCount": min(similar_count, 8),
                "generatedWithoutAI": False,
                "operations": reference_operations,
                "warnings": reference_warnings,
            },
            "hotContents": {
                "status": "complete" if hot_count >= 8 else "partial" if hot_count else "unavailable",
                "candidateCount": len(evidence.industry.hot_contents),
                "selectedCount": hot_count,
                "generatedWithoutAI": False,
                "operations": reference_operations,
                "warnings": reference_warnings,
            },
        }
        report_preview: dict[str, Any] = {
            "sourceMeta": source_meta_value,
        }
        self.store.update_progress(
            self.workflow_id,
            progress=75,
            current_stage="report_analysis",
            result_payload={
                "reportPreview": report_preview,
                "reportSectionsCompleted": [],
                "reportSectionsTotal": len(generation_specs),
                **({"reportSectionKey": requested_section_key} if requested_section_key else {}),
            },
        )

        async def generate_section(spec: ReportSectionSpec) -> tuple[str, Any]:
            try:
                prompt = build_report_section_prompt(
                    spec,
                    ai_context,
                    evidence,
                    source_meta_value,
                )
                raw = await self._complete(
                    prompt,
                    stage=f"report_analysis.{spec.key}",
                )
                try:
                    parsed = parse_report_section(raw, spec)
                except ValueError as exc:
                    logger.warning(
                        "account_report section validation failed; retrying "
                        "workflow_id=%s section=%s error=%s",
                        self.workflow_id,
                        spec.key,
                        str(exc),
                    )
                    retry_raw = await self._complete(
                        build_report_section_retry_prompt(prompt, spec),
                        stage=f"report_analysis.{spec.key}.retry",
                    )
                    parsed = parse_report_section(retry_raw, spec)
                return spec.key, _sanitize_report_section(spec.key, parsed, evidence)
            except Exception:
                if spec.key == "similarAccounts":
                    reference_fallbacks.add(spec.key)
                    return spec.key, [
                        item.model_dump(mode="json", by_alias=True)
                        for item in deterministic_similar_accounts(evidence)
                    ]
                if spec.key == "hotContents":
                    reference_fallbacks.add(spec.key)
                    return spec.key, [
                        item.model_dump(mode="json", by_alias=True)
                        for item in deterministic_hot_contents(evidence)
                    ]
                raise

        reference_fallbacks: set[str] = set()
        tasks = [asyncio.create_task(generate_section(spec)) for spec in generation_specs]
        section_values: dict[str, Any] = {}
        section_errors: list[Exception] = []
        for completed_task in asyncio.as_completed(tasks):
            try:
                key, value = await completed_task
            except Exception as exc:
                section_errors.append(exc)
                continue
            section_values[key] = value
            preview_key = "topBloggerDetails" if key == "topBloggers" else key
            report_preview[preview_key] = value
            report_preview["generatedAt"] = source_meta_value.get("generatedAt")
            completed_keys = [spec.key for spec in generation_specs if spec.key in section_values]
            progress = 75 + (len(completed_keys) * 18 // len(generation_specs))
            self.store.update_progress(
                self.workflow_id,
                progress=progress,
                current_stage="report_analysis",
                result_payload={
                    "reportPreview": dict(report_preview),
                    "reportSectionsCompleted": completed_keys,
                },
            )

        if section_errors:
            raise section_errors[0]

        for key in reference_fallbacks:
            source_meta_value["referenceDiscovery"][key]["generatedWithoutAI"] = True
            if source_meta_value["referenceDiscovery"][key]["status"] == "complete":
                source_meta_value["referenceDiscovery"][key]["status"] = "partial"

        report: AccountReportPayload | None = None
        if not requested_section_key:
            report = AccountReportPayload.model_validate(
                {**section_values, "sourceMeta": source_meta_value}
            )
            report = _filter_report_candidates(report, evidence)
            report = _merge_hot_content_urls(report, evidence)
            report = _merge_creator_display_data(report, evidence)
            _reject_verbatim_comments(report, evidence)
            report_value = report.model_dump(mode="json", by_alias=True)
            report_value["sourceMeta"] = source_meta_value
            report = AccountReportPayload.model_validate(report_value)

        self.store.update_progress(self.workflow_id, progress=95, current_stage="report_persistence")
        user_id = str(account.get("userId") or "")
        account_id = str(account.get("id") or "")
        if requested_section_key:
            persisted = self.store.update_account_report_sections(
                user_id,
                account_id,
                _section_persistence_payload(
                    requested_section_key,
                    section_values[requested_section_key],
                    source_meta_value,
                ),
            )
        else:
            assert report is not None
            persisted = self.store.replace_account_report(
                user_id,
                account_id,
                _persistence_payload(report),
            )
        return {
            "reportVersion": _report_version(persisted),
            **({"sectionKey": requested_section_key} if requested_section_key else {}),
        }
