"""账号报告的数据采集、分块 AI 分析与原子持久化 workflow。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from collections.abc import Sequence
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
from app.services.mediaspider.service import MediaCrawlerService
from app.services.social_retrieval import RetrievalBackend, backend_for_platform
from app.services.tikhub_service import TikHubCrawlService
from app.services.tikhub_service.failure import classify_tikhub_failure
from app.services.workflow.workflows.base import WorkflowRegister

from ..collection.keyword_parallel import crawl_keywords_with_cookie_pool
from ..collection.options import account_report_runtime_options
from ..collection.platforms import (
    CrawlPlan,
    build_crawl_plans,
    canonical_platform,
    owner_identifiers,
    owner_identifiers_from_plan,
)
from ..collection.creator_target import (
    is_recoverable_resolve_error,
    resolve_creator_profile_url,
)
from ..collection.progress import AccountReportCrawlProgressTracker, CrawlTarget
from ..domain.models import (
    AccountReportEvidence,
    AccountReportPayload,
    ContentEvidence,
    CurrentAccountEvidence,
    HotContent,
    IndustryEvidence,
    KeywordPlan,
    ReportEvidence,
    SourceMeta,
)
from ..evidence.builder import build_report_evidence
from ..evidence.fallbacks import (
    deterministic_hot_contents,
    deterministic_similar_accounts,
    hot_selection_reason,
    scrub_reason_text,
)
from ..evidence.hot_contents import (
    HOT_CONTENTS_DEFAULT_LIMIT,
    content_exclusion_key,
    select_balanced_hot_contents,
)
from ..generation.context import build_account_report_ai_context
from ..generation.keywords import refine_planned_keywords
from ..generation.prompts.report import build_keyword_planning_prompt
from ..generation.sections import (
    REPORT_SECTION_SPECS,
    ReportSectionSpec,
    build_report_section_prompt,
    build_report_section_retry_prompt,
    get_report_section_spec,
    parse_report_section,
)
from ..generation.target_profile import generate_target_user_profile
from ..similar_accounts.benchmark_generation import generate_benchmark_similar_accounts
from .base import BaseAccountReportWorkflow
from .persistence import (
    build_report_persistence_payload,
    build_section_persistence_payload,
    report_version,
)
from .types import ACCOUNT_REPORT_WORKFLOW_TYPE

logger = get_logger(__name__)

_MIN_RECOVERABLE_PARTIAL_CONTENTS = 10
_TOPIC_REFERENCE_POOL_LIMIT = 20
_HOT_CONTENTS_CANDIDATE_POOL_LIMIT = 80
# 首轮关键词采集已固定每词 2 页（最热+近半年）；不足 8 条继续翻页
_HOT_CONTENTS_SEARCH_PAGES = 2
_HOT_CONTENTS_PAGE_FILL_ATTEMPTS = 4
_HOT_CONTENTS_PAGE_FILL_STAGNANT_STOP = 2


def _merge_hot_content_evidence(
    existing: Sequence[Any],
    incoming: Sequence[Any],
    *,
    limit: int = _HOT_CONTENTS_CANDIDATE_POOL_LIMIT,
) -> list[Any]:
    """按平台+contentId 去重合并爆款证据，新页优先。"""

    merged: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for item in [*list(incoming or []), *list(existing or [])]:
        key = content_exclusion_key(item)
        if key is None or key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= max(1, int(limit or 1)):
            break
    return merged


def _hot_contents_candidate_pool(
    evidence: ReportEvidence,
    *,
    account_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """持久化关键词爬取候选，供爆款「重新生成」直接换批、不再重爬。"""

    from ..evidence.hot_contents import filter_strong_related_contents

    ranked = filter_strong_related_contents(
        list(evidence.industry.hot_contents),
        account_context=account_context,
    )
    pool: list[dict[str, Any]] = []
    for item in ranked[:_HOT_CONTENTS_CANDIDATE_POOL_LIMIT]:
        pool.append(
            {
                "platform": item.platform,
                "contentId": item.content_id,
                "title": item.title,
                "summary": item.summary,
                "publicUrl": item.public_url,
                "coverUrl": item.cover_url,
                "videoDownloadUrl": item.video_download_url,
                "contentType": item.content_type,
                "creatorHash": item.creator_hash,
                "creatorName": item.creator_name,
                "creatorDisplayName": item.creator_display_name,
                "creatorProfileUrl": item.creator_profile_url,
                "creatorAvatarUrl": item.creator_avatar_url,
                "sourceKeyword": item.source_keyword,
                "sourceOperation": item.source_operation,
                "sourceSort": item.source_sort,
                "publishedAt": item.published_at,
                "engagementScore": item.engagement_score,
                "hotScore": item.hot_score,
                "evidenceCompleteness": item.evidence_completeness,
                "metrics": _trusted_content_metrics(item),
            }
        )
    return pool


def _merge_hot_candidate_pool(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in [*list(existing or []), *list(incoming or [])]:
        if not isinstance(raw, dict):
            continue
        key = content_exclusion_key(raw)
        if key is None or key in seen:
            continue
        seen.add(key)
        merged.append(dict(raw))
        if len(merged) >= _HOT_CONTENTS_CANDIDATE_POOL_LIMIT:
            break
    return merged


def _hot_shown_key_dicts(
    keys: set[tuple[str, str]] | frozenset[tuple[str, str]] | None,
) -> list[dict[str, str]]:
    return [
        {"platform": platform, "contentId": content_id}
        for platform, content_id in sorted(keys or set())
    ]


def _extend_hot_shown_keys(
    existing: set[tuple[str, str]],
    selected: list[Any],
) -> set[tuple[str, str]]:
    next_keys = set(existing)
    for item in selected:
        key = content_exclusion_key(item)
        if key is not None:
            next_keys.add(key)
    return next_keys


def _available_hot_selection_count(
    candidate_pool: list[dict[str, Any]],
    *,
    exclude_hot_keys: set[tuple[str, str]],
    account_platforms: list[str],
    account_context: dict[str, Any] | None,
) -> int:
    evidence_items = _content_evidence_from_candidate_pool(candidate_pool)
    if not evidence_items:
        return 0
    return len(
        select_balanced_hot_contents(
            evidence_items,
            platforms=account_platforms,
            exclude_keys=exclude_hot_keys or None,
            account_context=account_context,
        )
    )


def _content_evidence_from_candidate_pool(
    pool: list[dict[str, Any]] | None,
) -> list[ContentEvidence]:
    items: list[ContentEvidence] = []
    for raw in list(pool or []):
        if not isinstance(raw, dict):
            continue
        platform = str(raw.get("platform") or "").strip()
        content_id = str(raw.get("contentId") or raw.get("content_id") or "").strip()
        if not platform or not content_id:
            continue
        metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
        content_type = str(raw.get("contentType") or raw.get("content_type") or "unknown").strip()
        if content_type not in {"image", "video", "unknown"}:
            content_type = "unknown"
        items.append(
            ContentEvidence(
                platform=platform,
                content_id=content_id,
                title=str(raw.get("title") or ""),
                summary=str(raw.get("summary") or ""),
                public_url=str(raw.get("publicUrl") or raw.get("public_url") or ""),
                cover_url=str(raw.get("coverUrl") or raw.get("cover_url") or ""),
                video_download_url=str(
                    raw.get("videoDownloadUrl") or raw.get("video_download_url") or ""
                ),
                content_type=content_type,  # type: ignore[arg-type]
                creator_hash=str(raw.get("creatorHash") or raw.get("creator_hash") or ""),
                creator_name=str(raw.get("creatorName") or raw.get("creator_name") or ""),
                creator_display_name=str(
                    raw.get("creatorDisplayName") or raw.get("creator_display_name") or ""
                ),
                creator_profile_url=str(
                    raw.get("creatorProfileUrl") or raw.get("creator_profile_url") or ""
                ),
                creator_avatar_url=str(
                    raw.get("creatorAvatarUrl") or raw.get("creator_avatar_url") or ""
                ),
                source_keyword=str(
                    raw.get("sourceKeyword") or raw.get("source_keyword") or ""
                ),
                source_operation=str(
                    raw.get("sourceOperation") or raw.get("source_operation") or ""
                ),
                source_sort=str(raw.get("sourceSort") or raw.get("source_sort") or ""),
                published_at=str(raw.get("publishedAt") or raw.get("published_at") or ""),
                liked_count=int(metrics.get("likedCount") or raw.get("liked_count") or 0),
                collected_count=int(
                    metrics.get("collectedCount") or raw.get("collected_count") or 0
                ),
                comment_count=int(
                    metrics.get("commentCount") or raw.get("comment_count") or 0
                ),
                share_count=int(metrics.get("shareCount") or raw.get("share_count") or 0),
                view_count=int(metrics.get("viewCount") or raw.get("view_count") or 0),
                engagement_score=int(
                    metrics.get("engagementScore")
                    or raw.get("engagementScore")
                    or raw.get("engagement_score")
                    or 0
                ),
                hot_score=float(
                    metrics.get("hotScore")
                    or raw.get("hotScore")
                    or raw.get("hot_score")
                    or 0
                ),
                evidence_completeness=float(
                    raw.get("evidenceCompleteness")
                    or raw.get("evidence_completeness")
                    or 0
                ),
            )
        )
    return items


@dataclass
class PlatformCrawlOutcome:
    current_account_results: list[CrawlResult]
    industry_results: list[CrawlResult]
    owner_hashes: set[str]
    failed_platforms: list[dict[str, str]]
    successful_crawls: int = 0


_JSON_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)


def _extract_json_object(raw: Any) -> dict[str, Any]:
    """从模型输出中提取顶层 JSON 对象（允许前后夹杂 tool/search 包装）。"""

    text = str(raw or "").lstrip("\ufeff").strip()
    match = _JSON_FENCE.fullmatch(text)
    if match:
        text = match.group(1).strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except (json.JSONDecodeError, TypeError):
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("检索词规划不是合法的完整 JSON")


def _strict_keyword_plan(raw: Any, account_context: dict[str, Any] | None = None) -> KeywordPlan:
    from ..generation.keywords import (
        SEARCH_KEYWORD_MAX,
        SEARCH_KEYWORD_MIN,
        _clean_keyword_list,
        is_person_name_keyword,
        search_keywords_from_pack,
    )

    value = _extract_json_object(raw)
    if not isinstance(value, dict):
        raise ValueError("检索词规划顶层必须是 JSON 对象")

    planned_keywords = _clean_keyword_list(
        value.get("keywords") or [],
        max_count=SEARCH_KEYWORD_MAX,
        min_len=4,
    )
    # 旧模型可能只给 core/longTail；只用来凑满 5 个检索词，不再落库词包
    if len(planned_keywords) < SEARCH_KEYWORD_MIN:
        planned_keywords = search_keywords_from_pack(
            core=_clean_keyword_list(value.get("core") or [], max_count=2, min_len=4),
            long_tail=_clean_keyword_list(
                value.get("longTail") or value.get("long_tail") or [],
                max_count=4,
                min_len=4,
            ),
            fallback_keywords=planned_keywords,
            max_count=SEARCH_KEYWORD_MAX,
        )
    min_count = SEARCH_KEYWORD_MIN
    max_count = SEARCH_KEYWORD_MAX
    if not account_context:
        if len(planned_keywords) < min_count:
            raise ValueError(
                f"检索词规划不足 {min_count} 个有效词（当前 {len(planned_keywords)} 个）"
            )
        return KeywordPlan.model_validate({"keywords": planned_keywords[:max_count]})

    seed = dict(account_context.get("benchmarkSeed") or {}) or None

    def _pad(base: list[str], candidates: list[str]) -> list[str]:
        out = list(base)
        seen = {item.lower() for item in out}
        for raw_item in candidates:
            text = str(raw_item or "").strip()[:12]
            if not text or len(text) < 4 or text.lower() in seen:
                continue
            if is_person_name_keyword(text, account_context, seed=seed):
                continue
            out.append(text)
            seen.add(text.lower())
            if len(out) >= max_count:
                break
        return out

    refined = refine_planned_keywords(
        planned_keywords,
        account_context,
        seed=seed,
        min_count=min_count,
        max_count=max_count,
    )
    if len(refined) < min_count:
        refined = refine_planned_keywords(
            list(dict.fromkeys([*planned_keywords, *refined])),
            account_context,
            seed=seed,
            min_count=1,
            max_count=max_count,
        )
    # 精炼后不足：用模型原词（已排除对标昵称）+ 账号文案补齐，避免 KeywordPlan 校验直接失败
    if len(refined) < min_count:
        refined = _pad(refined, planned_keywords)
    if len(refined) < min_count:
        account = dict(account_context.get("account") or {})
        refined = _pad(
            refined,
            [
                str(account.get("productService") or "").strip(),
                str(account.get("industry") or "").strip(),
                str(account.get("purpose") or "").strip(),
                str(account.get("conversionGoal") or "").strip(),
                str(account.get("description") or "").strip()[:12],
                *planned_keywords,
            ],
        )
    if len(refined) < min_count:
        raise ValueError(
            f"检索词规划不足 {min_count} 个有效词（当前 {len(refined)} 个），请完善账号定位后重试"
        )
    return KeywordPlan.model_validate({"keywords": refined[:max_count]})

async def _resolve_benchmark_seed_for_keywords(
    *,
    benchmark_accounts: dict[str, str],
    resolver: Any | None = None,
) -> dict[str, Any] | None:
    """关键词规划前解析对标账号公开资料，供模型贴合对标赛道。"""

    if not benchmark_accounts:
        return None
    from app.services.account_report.similar_accounts.resolver import SimilarAccountResolver

    resolver = resolver or SimilarAccountResolver()
    for platform, account_id in dict(benchmark_accounts).items():
        platform_name = str(platform or "").strip()
        raw_id = str(account_id or "").strip()
        if not platform_name or not raw_id:
            continue
        try:
            resolved = await resolver.resolve(platform=platform_name, account_id=raw_id)
        except Exception:
            continue
        if not isinstance(resolved, dict):
            continue
        name = str(resolved.get("name") or "").strip()
        description = str(resolved.get("description") or "").strip()
        if not name and not description:
            continue
        return {
            "platform": platform_name,
            "name": name or raw_id,
            "description": description,
            "followers": max(int(resolved.get("followers") or 0), 0),
            "recentTitles": [],
        }
    return None


def _failed_platform(platform: str, mode: str, reason: str) -> dict[str, str]:
    """只接受内部固定摘要，绝不回显底层异常、URL、请求头或凭证。"""
    return {"platform": platform, "mode": mode, "reason": reason}


def _candidate_key(platform: str, creator_hash: str) -> tuple[str, str] | None:
    canonical = canonical_platform(platform)
    if canonical is None:
        return None
    return canonical[1], str(creator_hash or "").strip()


def _content_candidate_key(
    platform: str, content_id: str
) -> tuple[str, str] | None:
    canonical = canonical_platform(platform)
    if canonical is None:
        return None
    normalized_content_id = str(content_id or "").strip()
    return (canonical[1], normalized_content_id) if normalized_content_id else None


def _filter_report_candidates(
    report: AccountReportPayload,
    evidence: ReportEvidence,
) -> AccountReportPayload:
    """热门内容仍只能选自证据；相似账号已改为对标+千问出号+爬虫补全，不再按关键词候选过滤。"""

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
        }
    )


def _merge_hot_content_urls(
    report: AccountReportPayload,
    evidence: ReportEvidence,
) -> AccountReportPayload:
    """AI 仅选择热门内容，链接、封面和指标始终以已采集证据为准。"""

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
                        "cover_url": source.cover_url if source else "",
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


def _restore_hot_content_media_fields(
    items: list[Any],
    evidence: ReportEvidence,
) -> list[dict[str, Any]]:
    """换批/分块写入前，用证据回填 publicUrl / coverUrl，避免模型空字段覆盖封面。"""

    trusted = {
        key: item
        for item in evidence.industry.hot_contents
        if (key := _content_candidate_key(item.platform, item.content_id)) is not None
    }
    restored: list[dict[str, Any]] = []
    for raw in list(items or []):
        if hasattr(raw, "model_dump"):
            payload = raw.model_dump(mode="json", by_alias=True)
        elif isinstance(raw, dict):
            payload = dict(raw)
        else:
            continue
        key = _content_candidate_key(
            str(payload.get("platform") or ""),
            str(payload.get("contentId") or payload.get("content_id") or ""),
        )
        source = trusted.get(key) if key is not None else None
        if source is not None:
            payload["publicUrl"] = source.public_url
            payload["coverUrl"] = source.cover_url
            payload["contentType"] = source.content_type
            payload["metrics"] = _trusted_content_metrics(source)
        restored.append(payload)
    return restored


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


def _topic_reference_pool(
    evidence: ReportEvidence,
    *,
    platforms: list[str] | None = None,
    account_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """为推荐选题保留爆款候选池：双平台各半、各自按点赞。"""

    selected = select_balanced_hot_contents(
        evidence.industry.hot_contents,
        limit=_TOPIC_REFERENCE_POOL_LIMIT,
        platforms=platforms,
        per_keyword=0,
        account_context=account_context,
    )
    pool = []
    for item in selected:
        pool.append(
            {
                "platform": item.platform,
                "contentId": item.content_id,
                "title": item.title,
                "summary": item.summary,
                "publicUrl": item.public_url,
                "coverUrl": item.cover_url,
                "contentType": item.content_type,
                "sourceKeyword": item.source_keyword,
                "sourceSort": item.source_sort,
                "publishedAt": item.published_at,
                "hotScore": item.hot_score,
                "metrics": _trusted_content_metrics(item),
            }
        )
    return pool


def _trusted_creator_metrics(source: Any) -> dict[str, int | float]:
    """账号公开指标以采集证据为准，禁止 AI 补造、改写或遗漏。"""

    metrics = {
        "fansCount": source.fans_count,
        "worksCount": source.works_count,
        "likedCount": source.liked_count,
    }
    return {key: value for key, value in metrics.items() if value > 0}


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
    def merge(item, sources):
        source = sources.get(_candidate_key(item.platform, item.creator_hash))
        if source is None:
            return item
        updates = {
            "profile_url": source.profile_url,
            "avatar_url": source.avatar_url,
            "metrics": _trusted_creator_metrics(source),
        }
        if source.display_name:
            updates["name"] = source.display_name
        return item.model_copy(update=updates)

    return report.model_copy(
        update={
            "similar_accounts": [
                merge(item, similar_sources) for item in report.similar_accounts
            ],
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
        report.model_dump(mode="json", by_alias=True, exclude_none=True),
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
        # 以 AI 筛选结果为准：只允许证据白名单内的账号，回填可信展示字段。
        # 不再用确定性 Top8 覆盖 AI 的取舍（行业弱相关账号可被 AI 丢掉）。
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
        sanitized = []
        for item in value:
            item_key = _candidate_key(item.platform, item.creator_hash)
            if item_key not in allowlist:
                continue
            source = sources[item_key]
            updates = {
                "profile_url": source.profile_url,
                "avatar_url": source.avatar_url,
                "metrics": _trusted_creator_metrics(source),
            }
            if source.display_name:
                updates["name"] = source.display_name
            reason = scrub_reason_text(
                getattr(item, "similarity_reason", "") or "",
                fallback=getattr(fallback, "similarity_reason", "") or "与当前账号定位接近，可作对标参考。",
            )
            updates["similarity_reason"] = reason[:500]
            contents = [
                str(text).strip()[:80]
                for text in (
                    list(getattr(item, "representative_contents", None) or [])
                    or list(getattr(fallback, "representative_contents", None) or [])
                    or list(source.representative_contents or [])
                )[:3]
                if str(text).strip()
            ]
            updates["representative_contents"] = contents
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
            existing_tags = [
                str(tag).strip()
                for tag in (getattr(item, "tags", None) or [])
                if str(tag or "").strip() and str(tag).strip() != "口播"
            ]
            sanitized.append(
                item.model_copy(
                    update={
                        "public_url": source.public_url,
                        "cover_url": source.cover_url,
                        "content_type": source.content_type,
                        "tags": existing_tags,
                        "metrics": _trusted_content_metrics(source),
                    }
                )
            )
        value = sanitized
    dumped = (
        [item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in value]
        if isinstance(value, list)
        else value.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    _reject_verbatim_comment_values(dumped, evidence)
    return dumped


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
class AccountReportWorkflow(BaseAccountReportWorkflow):
    type = ACCOUNT_REPORT_WORKFLOW_TYPE
    section_key: str | None = None

    async def _execute_context_only_target_profile(
        self,
        *,
        account: dict[str, Any],
        ai_context: dict[str, Any],
    ) -> dict[str, Any]:
        """不规划关键词、不采集作品，仅依据账号档案和知识库生成画像。"""

        section_key = "targetUserProfile"
        self.store.update_progress(
            self.workflow_id,
            progress=75,
            current_stage="report_analysis",
            result_payload={
                "reportPreview": {},
                "reportSectionsCompleted": [],
                "reportSectionsTotal": 1,
                "reportSectionKey": section_key,
            },
        )
        parsed = await generate_target_user_profile(
            complete=self._complete,
            ai_context=ai_context,
            workflow_id=self.workflow_id,
        )
        value = parsed.model_dump(mode="json", by_alias=True, exclude_none=True)
        self.store.update_progress(
            self.workflow_id,
            progress=93,
            current_stage="report_analysis",
            result_payload={
                "reportPreview": {section_key: value},
                "reportSectionsCompleted": [section_key],
            },
        )
        self.store.update_progress(
            self.workflow_id,
            progress=95,
            current_stage="report_persistence",
        )
        persisted = self.store.update_account_report_sections(
            str(account.get("userId") or ""),
            str(account.get("id") or ""),
            build_section_persistence_payload(section_key, value, None),
        )
        return {
            "reportVersion": report_version(persisted),
            "sectionKey": section_key,
        }

    async def _crawl_hot_contents_search_page(
        self,
        *,
        account: dict[str, Any],
        account_platforms: list[str],
        keywords: list[str],
        search_page: int,
        links: dict[str, Any],
        reference_comments: bool = False,
    ) -> list[CrawlResult]:
        """按已有关键词翻一页搜索，给爆款换批补货。"""

        plans, _unsupported = build_crawl_plans(account, links)
        crawl_plans = [
            plan for plan in plans if plan.platform_code in {"xhs", "dy"}
        ]
        if not crawl_plans or not keywords:
            return []

        runtime_settings = self.context.get("_settings") or settings
        injected_crawler = self.context.get("_crawler_service")
        injected_cookie_pool_loader = self.context.get("_cookie_pool_loader")
        cookie_pool_loader = (
            injected_cookie_pool_loader
            if injected_cookie_pool_loader is not None
            else load_cookie_pool
        )
        cookie_pool = cookie_pool_loader()
        crawler = injected_crawler or MediaCrawlerService()
        page = max(1, int(search_page or 1))

        async def _crawl_one(plan) -> CrawlResult | None:
            if cookie_pool is None or not cookie_pool.has_cookies(plan.platform_code):
                logger.warning(
                    "hot contents page crawl skipped: missing cookies platform=%s",
                    plan.platform_code,
                )
                return None
            runtime_options = account_report_runtime_options(
                runtime_settings,
                plan.platform_code,
                reference_comments=reference_comments,
                backend=backend_for_platform(runtime_settings, plan.platform_code),
            )
            page_size = 20 if plan.platform_code == "xhs" else 10
            runtime_options["max_notes_count"] = page_size
            runtime_options["start_page"] = page
            try:
                return await crawl_keywords_with_cookie_pool(
                    platform=plan.platform_code,
                    crawler=crawler,
                    cookie_pool=cookie_pool,
                    keywords=keywords,
                    runtime_options=runtime_options,
                )
            except Exception as exc:
                logger.warning(
                    "hot contents page crawl failed platform=%s page=%s error=%s",
                    plan.platform_code,
                    page,
                    exc,
                )
                return None

        crawled = await asyncio.gather(*[_crawl_one(plan) for plan in crawl_plans])
        return [item for item in crawled if item is not None]

    async def _top_up_hot_contents_until_quota(
        self,
        *,
        evidence: ReportEvidence,
        candidate_pool: list[dict[str, Any]],
        account: dict[str, Any],
        account_platforms: list[str],
        keywords: list[str],
        ai_context: dict[str, Any],
        exclude_hot_keys: set[tuple[str, str]] | None = None,
        links: dict[str, Any] | None = None,
        reference_comments: bool = False,
        start_page: int = 2,
        max_attempts: int = _HOT_CONTENTS_PAGE_FILL_ATTEMPTS,
    ) -> tuple[ReportEvidence, list[dict[str, Any]], int, list[str]]:
        """首批强相关爆款不足 8 条时，按关键词继续翻页补货。"""

        pool = [dict(item) for item in candidate_pool if isinstance(item, dict)]
        shown_keys = set(exclude_hot_keys or set())
        next_search_page = max(2, int(start_page or 2))
        operations: list[str] = []
        available = _available_hot_selection_count(
            pool,
            exclude_hot_keys=shown_keys,
            account_platforms=account_platforms,
            account_context=ai_context,
        )
        page_attempts = 0
        hot_list = list(evidence.industry.hot_contents)
        filled = False
        stagnant_pages = 0

        while (
            available < HOT_CONTENTS_DEFAULT_LIMIT
            and page_attempts < max(0, int(max_attempts or 0))
        ):
            store = getattr(self, "store", None)
            if store is not None:
                store.update_progress(
                    self.workflow_id,
                    progress=70,
                    current_stage="hot_contents_fill",
                    result_payload={
                        "hotContentsFill": {
                            "page": next_search_page,
                            "available": available,
                            "target": HOT_CONTENTS_DEFAULT_LIMIT,
                        }
                    },
                )
            page_results = await self._crawl_hot_contents_search_page(
                account=account,
                account_platforms=account_platforms,
                keywords=keywords,
                search_page=next_search_page,
                links=dict(links or {}),
                reference_comments=reference_comments,
            )
            page_attempts += 1
            if not page_results:
                break
            if "hot_contents_search_page" not in operations:
                operations.append("hot_contents_search_page")
            page_evidence = build_report_evidence(
                [],
                page_results,
                set(evidence.owner_hashes or []),
            )
            page_hot = list(page_evidence.industry.hot_contents)
            if not page_hot:
                next_search_page += 1
                stagnant_pages += 1
                if stagnant_pages >= _HOT_CONTENTS_PAGE_FILL_STAGNANT_STOP:
                    operations.append("hot_contents_fill_early_stop")
                    break
                continue
            prev_available = available
            hot_list = _merge_hot_content_evidence(hot_list, page_hot)
            pool = _merge_hot_candidate_pool(
                _hot_contents_candidate_pool(page_evidence, account_context=ai_context),
                pool,
            )
            next_search_page += 1
            filled = True
            available = _available_hot_selection_count(
                pool,
                exclude_hot_keys=shown_keys,
                account_platforms=account_platforms,
                account_context=ai_context,
            )
            logger.info(
                "hot contents page fill workflow_id=%s page=%s available=%s target=%s",
                self.workflow_id,
                next_search_page - 1,
                available,
                HOT_CONTENTS_DEFAULT_LIMIT,
            )
            if available <= prev_available:
                stagnant_pages += 1
                if stagnant_pages >= _HOT_CONTENTS_PAGE_FILL_STAGNANT_STOP:
                    operations.append("hot_contents_fill_early_stop")
                    break
            else:
                stagnant_pages = 0

        if filled:
            evidence = evidence.model_copy(
                update={
                    "industry": evidence.industry.model_copy(
                        update={
                            "hot_contents": hot_list[:_HOT_CONTENTS_CANDIDATE_POOL_LIMIT]
                        }
                    )
                }
            )
        return evidence, pool, next_search_page, operations

    async def _execute_hot_contents_from_cache(
        self,
        *,
        account: dict[str, Any],
        ai_context: dict[str, Any],
        account_platforms: list[str],
        candidate_pool: list[dict[str, Any]],
        exclude_hot_keys: set[tuple[str, str]],
        keywords: list[str],
        search_page: int = 2,
        links: dict[str, Any] | None = None,
        reference_comments: bool = False,
    ) -> dict[str, Any]:
        """爆款重新生成：优先用候选池；不够则按关键词翻页补货，且不与历史批次重复。"""

        section_key = "hotContents"
        pool = [dict(item) for item in candidate_pool if isinstance(item, dict)]
        operations = ["hot_contents_candidate_cache"]
        next_search_page = max(2, int(search_page or 2))
        shown_keys = set(exclude_hot_keys or set())

        available = _available_hot_selection_count(
            pool,
            exclude_hot_keys=shown_keys,
            account_platforms=account_platforms,
            account_context=ai_context,
        )
        # 候选不够凑满一批时翻页补货；新页优先写入池，避免旧已展示条目占满 80 上限
        page_attempts = 0
        stagnant_pages = 0
        while (
            available < HOT_CONTENTS_DEFAULT_LIMIT
            and page_attempts < _HOT_CONTENTS_PAGE_FILL_ATTEMPTS
        ):
            prev_available = available
            page_results = await self._crawl_hot_contents_search_page(
                account=account,
                account_platforms=account_platforms,
                keywords=keywords,
                search_page=next_search_page,
                links=dict(links or {}),
                reference_comments=reference_comments,
            )
            page_attempts += 1
            if not page_results:
                break
            if "hot_contents_search_page" not in operations:
                operations.append("hot_contents_search_page")
            page_evidence = build_report_evidence([], page_results, set())
            pool = _merge_hot_candidate_pool(
                _hot_contents_candidate_pool(page_evidence),
                pool,
            )
            next_search_page += 1
            available = _available_hot_selection_count(
                pool,
                exclude_hot_keys=shown_keys,
                account_platforms=account_platforms,
                account_context=ai_context,
            )
            if available <= prev_available:
                stagnant_pages += 1
                if stagnant_pages >= _HOT_CONTENTS_PAGE_FILL_STAGNANT_STOP:
                    operations.append("hot_contents_fill_early_stop")
                    break
            else:
                stagnant_pages = 0

        hot_contents = _content_evidence_from_candidate_pool(pool)
        if not hot_contents:
            raise ValueError("暂无可用的爆款候选缓存，请先完整生成一次账号报告")
        if available <= 0:
            raise ValueError("爆款候选已用尽且翻页未拿到新内容，请稍后再试或重新生成整份报告")

        evidence = AccountReportEvidence(
            currentAccountEvidence=CurrentAccountEvidence(),
            industryEvidence=IndustryEvidence(hotContents=hot_contents),
            ownerHashes=[],
        )
        source_meta_value = {
            "platforms": account_platforms or ["视频号"],
            "keywords": list(keywords),
            "sampleCount": len(hot_contents),
            "failedPlatforms": [],
            "unsupportedPlatforms": [],
            "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "hotContentsCandidatePool": list(pool),
            "hotContentsSearchPage": next_search_page,
            "hotContentsShownKeys": _hot_shown_key_dicts(shown_keys),
            "referenceDiscovery": {
                "hotContents": {
                    "status": "complete",
                    "candidateCount": len(hot_contents),
                    "selectedCount": 0,
                    "generatedWithoutAI": False,
                    "operations": list(operations),
                    "warnings": [],
                    "searchPage": next_search_page,
                }
            },
        }
        selected_count = len(
            select_balanced_hot_contents(
                evidence.industry.hot_contents,
                platforms=account_platforms,
                exclude_keys=shown_keys or None,
                account_context=ai_context,
            )
        )
        source_meta_value["referenceDiscovery"]["hotContents"]["selectedCount"] = (
            selected_count
        )
        source_meta_value["referenceDiscovery"]["hotContents"]["status"] = (
            "complete"
            if selected_count >= HOT_CONTENTS_DEFAULT_LIMIT
            else "partial"
            if selected_count
            else "unavailable"
        )

        self.store.update_progress(
            self.workflow_id,
            progress=75,
            current_stage="report_analysis",
            result_payload={
                "reportPreview": {"sourceMeta": source_meta_value},
                "reportSectionsCompleted": [],
                "reportSectionsTotal": 1,
                "reportSectionKey": section_key,
            },
        )

        spec = get_report_section_spec(section_key)
        try:
            prompt = build_report_section_prompt(
                spec,
                ai_context,
                evidence,
                source_meta_value,
                exclude_hot_keys=shown_keys or None,
            )
            raw = await self._complete(
                prompt,
                stage=f"report_analysis.{section_key}",
            )
            try:
                parsed = parse_report_section(raw, spec)
            except ValueError as exc:
                logger.warning(
                    "account_report section validation failed; retrying "
                    "workflow_id=%s section=%s error=%s",
                    self.workflow_id,
                    section_key,
                    str(exc),
                )
                retry_raw = await self._complete(
                    build_report_section_retry_prompt(prompt, spec),
                    stage=f"report_analysis.{section_key}.retry",
                )
                parsed = parse_report_section(retry_raw, spec)
            value = _sanitize_report_section(
                section_key,
                parsed,
                evidence,
                platforms=account_platforms,
                exclude_hot_keys=shown_keys or None,
                account_context=ai_context,
            )
        except Exception:
            source_meta_value["referenceDiscovery"]["hotContents"][
                "generatedWithoutAI"
            ] = True
            if source_meta_value["referenceDiscovery"]["hotContents"]["status"] == "complete":
                source_meta_value["referenceDiscovery"]["hotContents"]["status"] = "partial"
            value = [
                item.model_dump(mode="json", by_alias=True)
                for item in deterministic_hot_contents(
                    evidence,
                    platforms=account_platforms,
                    exclude_keys=shown_keys or None,
                    account_context=ai_context,
                )
            ]

        # 换批不走整份报告的 _merge_hot_content_urls，这里强制回填封面/链接
        value = _restore_hot_content_media_fields(list(value or []), evidence)

        next_shown = _extend_hot_shown_keys(shown_keys, list(value or []))
        source_meta_value["hotContentsShownKeys"] = _hot_shown_key_dicts(next_shown)
        source_meta_value["hotContentsSearchPage"] = next_search_page
        source_meta_value["hotContentsCandidatePool"] = list(pool)
        source_meta_value["referenceDiscovery"]["hotContents"]["selectedCount"] = len(
            value or []
        )

        self.store.update_progress(
            self.workflow_id,
            progress=93,
            current_stage="report_analysis",
            result_payload={
                "reportPreview": {section_key: value, "sourceMeta": source_meta_value},
                "reportSectionsCompleted": [section_key],
            },
        )
        self.store.update_progress(
            self.workflow_id,
            progress=95,
            current_stage="report_persistence",
        )
        persisted = self.store.update_account_report_sections(
            str(account.get("userId") or ""),
            str(account.get("id") or ""),
            build_section_persistence_payload(section_key, value, source_meta_value),
        )
        return {
            "reportVersion": report_version(persisted),
            "sectionKey": section_key,
        }

    async def _generate_benchmark_similar_section(
        self,
        *,
        account: dict[str, Any],
        target_fans_wan: float | None = None,
        report_keywords: list[str] | None = None,
        search_results: list[CrawlResult] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        injected_complete = self.context.get("_benchmark_complete") or self._complete
        runtime_settings = self.context.get("_settings") or settings
        injected_crawler = self.context.get("_crawler_service")
        injected_cookie_pool_loader = self.context.get("_cookie_pool_loader")
        cookie_pool_loader = (
            injected_cookie_pool_loader
            if injected_cookie_pool_loader is not None
            else load_cookie_pool
        )
        crawler = injected_crawler or MediaCrawlerService()
        cookie_pool_holder: dict[str, Any] = {}

        def _cookie_pool():
            if "pool" not in cookie_pool_holder:
                cookie_pool_holder["pool"] = cookie_pool_loader()
            return cookie_pool_holder["pool"]

        async def keyword_crawl(*, platform_name: str, keywords: list[str]):
            platform_code = normalize_platform(platform_name)
            runtime_options = account_report_runtime_options(
                runtime_settings,
                platform_code,
            )
            from app.services.account_report.similar_accounts.benchmark_generation import (
                SIMILAR_KEYWORD_NOTES_LIMIT,
                _crawl_similar_keywords_hybrid,
            )

            # 相似博主：用户搜索 + 笔记搜索双通道，单独放量
            runtime_options["max_notes_count"] = max(1, int(SIMILAR_KEYWORD_NOTES_LIMIT))
            return await _crawl_similar_keywords_hybrid(
                crawler=crawler,
                cookie_pool=_cookie_pool(),
                platform_code=platform_code,
                keywords=keywords,
                runtime_options=runtime_options,
            )

        async def creator_crawl(*, profile_url: str, platform_name: str):
            platform_code = normalize_platform(platform_name)
            runtime_options = account_report_runtime_options(
                runtime_settings,
                platform_code,
            )
            runtime_options["max_notes_count"] = min(
                int(runtime_options.get("max_notes_count") or 8),
                8,
            )
            # 代表内容只需列表标题，跳过详情可显著降低限流
            runtime_options["max_detail_count"] = 0
            runtime_options["enable_comments"] = False
            runtime_options["enable_sub_comments"] = False

            async def _run(cookie: str):
                return await crawler.crawl_by_creator(
                    creator_url=profile_url,
                    cookies=cookie,
                    **runtime_options,
                )

            return await run_with_cookie_candidates(_cookie_pool(), platform_code, _run)

        async def note_search(*, platform_name: str, keyword: str):
            platform_code = normalize_platform(platform_name)
            runtime_options = account_report_runtime_options(
                runtime_settings,
                platform_code,
            )
            runtime_options["max_notes_count"] = min(
                int(runtime_options.get("max_notes_count") or 20),
                20,
            )
            runtime_options["max_detail_count"] = 0
            runtime_options["enable_comments"] = False
            runtime_options["enable_sub_comments"] = False
            # 综合笔记搜索：按昵称匹配作者作品标题（同样按最多点赞）
            runtime_options["search_channel"] = "general"
            runtime_options["search_sort"] = "most_like"
            return await crawl_keywords_with_cookie_pool(
                crawler=crawler,
                cookie_pool=_cookie_pool(),
                platform=platform_code,
                keywords=[str(keyword or "").strip()],
                runtime_options=runtime_options,
            )

        result = await generate_benchmark_similar_accounts(
            account=account,
            target_fans_wan=target_fans_wan,
            complete=injected_complete,
            resolver=self.context.get("_similar_account_resolver"),
            keyword_crawl=keyword_crawl,
            creator_crawl=creator_crawl,
            note_search=note_search,
            report_keywords=report_keywords,
        )
        return result.similar_accounts, result.discovery

    async def _execute_benchmark_similar_accounts(
        self,
        *,
        account: dict[str, Any],
        target_fans_wan: float | None = None,
        report_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """按账号定位 + 目标粉丝数（万）召回相似账号。"""

        section_key = "similarAccounts"
        self.store.update_progress(
            self.workflow_id,
            progress=40,
            current_stage="report_analysis",
            result_payload={
                "reportPreview": {},
                "reportSectionsCompleted": [],
                "reportSectionsTotal": 1,
                "reportSectionKey": section_key,
            },
        )
        value, discovery = await self._generate_benchmark_similar_section(
            account=account,
            target_fans_wan=target_fans_wan,
            report_keywords=report_keywords,
        )
        platforms = [
            str(item).strip()
            for item in (account.get("platforms") or [account.get("platform")])
            if str(item or "").strip()
        ] or ["抖音"]
        source_meta_value = {
            "platforms": platforms,
            "keywords": [],
            "sampleCount": len(value),
            "failedPlatforms": [],
            "unsupportedPlatforms": [],
            "generatedAt": datetime.now(UTC).isoformat(),
            "similarTargetFansWan": target_fans_wan,
            "referenceDiscovery": {
                "similarAccounts": discovery,
            },
        }
        self.store.update_progress(
            self.workflow_id,
            progress=93,
            current_stage="report_analysis",
            result_payload={
                "reportPreview": {section_key: value, "sourceMeta": source_meta_value},
                "reportSectionsCompleted": [section_key],
            },
        )
        self.store.update_progress(
            self.workflow_id,
            progress=95,
            current_stage="report_persistence",
        )
        persisted = self.store.update_account_report_sections(
            str(account.get("userId") or ""),
            str(account.get("id") or ""),
            build_section_persistence_payload(section_key, value, source_meta_value),
        )
        return {
            "reportVersion": report_version(persisted),
            "sectionKey": section_key,
        }

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
        account_platforms = [
            str(item).strip()
            for item in (account.get("platforms") or [account.get("platform")])
            if str(item or "").strip()
        ]
        exclude_hot_keys: set[tuple[str, str]] = set()
        # 整份报告刷新或单独换一批爆款：都避开上一批爆款 + 选题已用原文
        for raw in list(context.get("previousHotContents") or []):
            if not isinstance(raw, dict):
                continue
            key = content_exclusion_key(raw)
            if key is not None:
                exclude_hot_keys.add(key)
        links = dict(context.get("accountLinks") or {})
        raw_fans_wan = context.get("similarTargetFansWan")
        try:
            target_fans_wan = (
                float(raw_fans_wan)
                if raw_fans_wan is not None and raw_fans_wan != ""
                else None
            )
        except (TypeError, ValueError):
            target_fans_wan = None
        if target_fans_wan is not None and target_fans_wan <= 0:
            target_fans_wan = None
        ai_context = build_account_report_ai_context(
            account,
            knowledge_enabled=bool(context.get("knowledgeEnabled")),
            knowledge_context=str(context.get("knowledgeContext") or ""),
        )
        if requested_section_key == "targetUserProfile":
            return await self._execute_context_only_target_profile(
                account=account,
                ai_context=ai_context,
            )
        if requested_section_key == "similarAccounts":
            report_keywords = [
                str(item or "").strip()
                for item in list(context.get("reportKeywords") or [])
                if str(item or "").strip()
            ]
            return await self._execute_benchmark_similar_accounts(
                account=account,
                target_fans_wan=target_fans_wan,
                report_keywords=report_keywords or None,
            )
        if requested_section_key == "hotContents":
            cached_pool = [
                item
                for item in list(context.get("hotContentsCandidatePool") or [])
                if isinstance(item, dict)
            ]
            if cached_pool:
                return await self._execute_hot_contents_from_cache(
                    account=account,
                    ai_context=ai_context,
                    account_platforms=account_platforms,
                    candidate_pool=cached_pool,
                    exclude_hot_keys=exclude_hot_keys,
                    keywords=[
                        str(item or "").strip()
                        for item in list(context.get("reportKeywords") or [])
                        if str(item or "").strip()
                    ],
                    search_page=int(context.get("hotContentsSearchPage") or 2),
                    links=links,
                    reference_comments=reference_comments,
                )
        plans, unsupported = build_crawl_plans(account, links)
        if not plans and unsupported != ["视频号"]:
            raise ValueError("账号未配置可生成报告的平台")

        runtime_settings = self.context.get("_settings") or settings
        injected_crawler = self.context.get("_crawler_service")
        injected_cookie_pool_loader = self.context.get("_cookie_pool_loader")
        backend_by_platform = {
            plan.platform_code: (
                (
                    RetrievalBackend.MEDIASPIDER
                    if injected_cookie_pool_loader is not None
                    else RetrievalBackend.TIKHUB
                )
                if injected_crawler is not None
                else (
                    RetrievalBackend.TIKHUB
                    if reference_comments
                    else backend_for_platform(
                        runtime_settings,
                        plan.platform_code,
                    )
                )
            )
            for plan in plans
        }
        mediaspider_enabled = any(
            backend == RetrievalBackend.MEDIASPIDER
            for backend in backend_by_platform.values()
        )
        cookie_pool_loader = (
            injected_cookie_pool_loader
            if injected_cookie_pool_loader is not None
            else (load_cookie_pool if mediaspider_enabled else None)
        )
        current_account_results: list[CrawlResult] = []
        owner_hashes: set[str] = set()
        failed_platforms: list[dict[str, str]] = []
        dashboard_source = self.context.get("_dashboard_source")
        dashboard_plans = [
            plan
            for plan in plans
            if backend_by_platform[plan.platform_code] == RetrievalBackend.TIKHUB
        ]
        if dashboard_plans and dashboard_source is not None:
            self.store.update_progress(
                self.workflow_id,
                progress=8,
                current_stage="dashboard_refresh",
            )
            dashboard_evidence = await dashboard_source.prepare(
                user_id=str(account.get("userId") or ""),
                account_id=str(account.get("id") or ""),
                platform_names=[plan.platform_name for plan in dashboard_plans],
            )
            current_account_results.extend(dashboard_evidence.results)
            owner_hashes.update(dashboard_evidence.owner_hashes)
            failed_platforms.extend(dashboard_evidence.failures)

        self.store.update_progress(self.workflow_id, progress=10, current_stage="keyword_planning")
        keywords: list[str] = []
        if plans:
            benchmark_accounts = dict(account.get("benchmarkAccounts") or {})
            try:
                benchmark_seed = await _resolve_benchmark_seed_for_keywords(
                    benchmark_accounts=benchmark_accounts,
                )
            except Exception:
                benchmark_seed = None
            if benchmark_seed:
                ai_context = {
                    **ai_context,
                    "benchmarkSeed": benchmark_seed,
                }
            keywords = _strict_keyword_plan(
                await self._complete(
                    build_keyword_planning_prompt(
                        ai_context,
                        benchmark_seed=benchmark_seed,
                    ),
                    stage="keyword_planning",
                ),
                ai_context,
            ).keywords

        mediaspider_crawler = MediaCrawlerService()
        tikhub_crawler = TikHubCrawlService()
        cookie_pool = cookie_pool_loader() if cookie_pool_loader is not None else None
        industry_results: list[CrawlResult] = []
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
                backend=backend_by_platform[plan.platform_code],
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
            backend = backend_by_platform[plan.platform_code]
            use_mediaspider = backend == RetrievalBackend.MEDIASPIDER
            crawler = injected_crawler or (
                mediaspider_crawler if use_mediaspider else tikhub_crawler
            )
            if use_mediaspider and (
                cookie_pool is None
                or not cookie_pool.has_cookies(plan.platform_code)
            ):
                outcome.failed_platforms.append(
                    record_failure(
                        plan,
                        mode="configuration",
                        failure=missing_credentials,
                        compatible_reason="未配置平台凭证",
                    )
                )
                return outcome
            planned_owner_hashes = owner_identifiers_from_plan(plan)
            outcome.owner_hashes.update(planned_owner_hashes)
            if plan.creator_url and use_mediaspider:
                if not planned_owner_hashes:
                    record_notice(plan, mode="creator")
                else:
                    try:
                        async def crawl_creator(cookie: str = ""):
                            return await crawler.crawl_by_creator(
                                creator_url=plan.creator_url,
                                on_progress=tracker.callback(
                                    plan.platform_name,
                                    "creator",
                                ),
                                cookies=cookie,
                                **runtime_options,
                            )

                        creator_result = await run_with_cookie_candidates(
                            cookie_pool,
                            plan.platform_code,
                            crawl_creator,
                        )
                        content_count, creator_count, comment_count = result_counts(
                            creator_result
                        )
                        if content_count == 0 and creator_count == 0:
                            record_notice(plan, mode="creator")
                        else:
                            outcome.current_account_results.append(creator_result)
                            creator_identifiers = owner_identifiers(creator_result)
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
                                    owner_identifiers(partial_result)
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
            elif not plan.creator_url:
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
                        **({"cookies": cookie} if use_mediaspider else {}),
                        **runtime_options,
                    )

                keyword_result = (
                    await crawl_keywords_with_cookie_pool(
                        crawler=crawler,
                        cookie_pool=cookie_pool,
                        platform=plan.platform_code,
                        keywords=keywords,
                        runtime_options=runtime_options,
                        on_progress=tracker.callback(
                            plan.platform_name,
                            "keyword",
                        ),
                    )
                    if use_mediaspider
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
                            (
                                classify_tikhub_failure(exc)
                                if backend == RetrievalBackend.TIKHUB
                                else None
                            )
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
        source_meta_value["hotContentsCandidatePool"] = _hot_contents_candidate_pool(
            evidence,
            account_context=ai_context,
        )
        source_meta_value["hotContentsSearchPage"] = 2
        source_meta_value["hotContentsShownKeys"] = []
        if target_fans_wan is not None:
            source_meta_value["similarTargetFansWan"] = target_fans_wan
        source_meta_value.pop("benchmarkAccounts", None)
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
        similar_count = 0
        hot_count = len(
            select_balanced_hot_contents(
                evidence.industry.hot_contents,
                platforms=account_platforms,
                exclude_keys=exclude_hot_keys or None,
                account_context=ai_context,
            )
        )
        source_meta_value["referenceDiscovery"] = {
            "similarAccounts": {
                "status": "pending",
                "candidateCount": 0,
                "selectedCount": 0,
                "generatedWithoutAI": False,
                "mode": "benchmark_qwen_keyword_rerank",
                "operations": [
                    "benchmark_crawl",
                    "benchmark_recent_contents",
                    "qwen_infer_style_and_keywords",
                    "keyword_batch_crawl",
                    "candidate_seed_rank",
                    "candidate_enrich",
                    "fans_top_per_platform",
                    "platform_similar_unavailable",
                ],
                "warnings": [],
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

        async def finalize_section(key: str, value: Any) -> tuple[str, Any]:
            if key != "hotContents" or not isinstance(value, list):
                return key, value
            shown = _extend_hot_shown_keys(set(exclude_hot_keys or set()), list(value or []))
            source_meta_value["hotContentsShownKeys"] = _hot_shown_key_dicts(shown)
            source_meta_value["hotContentsSearchPage"] = max(
                _HOT_CONTENTS_SEARCH_PAGES + 1,
                int(source_meta_value.get("hotContentsSearchPage") or (_HOT_CONTENTS_SEARCH_PAGES + 1)),
            )
            return key, value

        async def generate_section(spec: ReportSectionSpec) -> tuple[str, Any]:
            try:
                if spec.key == "similarAccounts":
                    value, discovery = await self._generate_benchmark_similar_section(
                        account=account,
                        target_fans_wan=target_fans_wan,
                        report_keywords=keywords,
                    )
                    source_meta_value["referenceDiscovery"]["similarAccounts"] = discovery
                    return await finalize_section(spec.key, value)
                if spec.key == "targetUserProfile":
                    parsed = await generate_target_user_profile(
                        complete=self._complete,
                        ai_context=ai_context,
                        workflow_id=self.workflow_id,
                    )
                    return await finalize_section(
                        spec.key,
                        _sanitize_report_section(
                            spec.key,
                            parsed,
                            evidence,
                            platforms=account_platforms,
                            exclude_hot_keys=exclude_hot_keys or None,
                            account_context=ai_context,
                        ),
                    )
                prompt = build_report_section_prompt(
                    spec,
                    ai_context,
                    evidence,
                    source_meta_value,
                    exclude_hot_keys=exclude_hot_keys or None,
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
                return await finalize_section(
                    spec.key,
                    _sanitize_report_section(
                        spec.key,
                        parsed,
                        evidence,
                        platforms=account_platforms,
                        exclude_hot_keys=exclude_hot_keys or None,
                        account_context=ai_context,
                    ),
                )
            except Exception:
                if spec.key == "similarAccounts":
                    reference_fallbacks.add(spec.key)
                    source_meta_value["referenceDiscovery"]["similarAccounts"] = {
                        "status": "unavailable",
                        "candidateCount": 0,
                        "selectedCount": 0,
                        "generatedWithoutAI": True,
                        "mode": "benchmark_qwen_keyword_rerank",
                        "operations": [
                            "benchmark_crawl",
                            "benchmark_recent_contents",
                            "qwen_infer_style_and_keywords",
                            "keyword_batch_crawl",
                            "candidate_seed_rank",
                            "candidate_enrich",
                            "fans_top_per_platform",
                            "platform_similar_unavailable",
                        ],
                        "warnings": ["benchmark_similar_generation_failed"],
                    }
                    return await finalize_section(spec.key, [])
                if spec.key == "hotContents":
                    reference_fallbacks.add(spec.key)
                    return await finalize_section(
                        spec.key,
                        [
                            item.model_dump(mode="json", by_alias=True)
                            for item in deterministic_hot_contents(
                                evidence,
                                platforms=account_platforms,
                                exclude_keys=exclude_hot_keys or None,
                                account_context=ai_context,
                            )
                        ],
                    )
                raise

        reference_fallbacks: set[str] = set()
        section_values: dict[str, Any] = {}
        section_errors: list[Exception] = []

        def _record_section(key: str, value: Any) -> None:
            section_values[key] = value
            report_preview[key] = value
            report_preview["generatedAt"] = source_meta_value.get("generatedAt")
            completed_keys = [
                spec.key for spec in generation_specs if spec.key in section_values
            ]
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

        async def _run_section_batch(
            specs: list[ReportSectionSpec],
            *,
            sequential: bool,
        ) -> None:
            if not specs:
                return
            if sequential:
                # 画像/违禁词/爆款串行：避免并行打满同一中转站后互相拖死。
                for spec in specs:
                    self.store.update_progress(
                        self.workflow_id,
                        progress=75
                        + (len(section_values) * 18 // max(len(generation_specs), 1)),
                        current_stage="report_analysis",
                        result_payload={
                            "reportPreview": dict(report_preview),
                            "reportSectionsCompleted": [
                                item.key
                                for item in generation_specs
                                if item.key in section_values
                            ],
                            "reportSectionKey": spec.key,
                        },
                    )
                    try:
                        key, value = await generate_section(spec)
                    except Exception as exc:
                        section_errors.append(exc)
                        return
                    _record_section(key, value)
                return

            tasks = [asyncio.create_task(generate_section(spec)) for spec in specs]
            try:
                for completed_task in asyncio.as_completed(tasks):
                    try:
                        key, value = await completed_task
                    except Exception as exc:
                        section_errors.append(exc)
                        continue
                    _record_section(key, value)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        # 先串行跑画像/合规/爆款，再跑相似博主（大量主页判定）。
        # 串行 + 单次超时，避免三路千问并行时画像/违禁词假死。
        # 画像/违禁词优先于爆款，避免用户最关心的两段排在后面。
        _fast_order = ("complianceRules", "targetUserProfile", "hotContents")
        fast_by_key = {
            spec.key: spec
            for spec in generation_specs
            if spec.key != "similarAccounts"
        }
        fast_specs = [
            fast_by_key[key] for key in _fast_order if key in fast_by_key
        ]
        fast_specs.extend(
            spec
            for spec in generation_specs
            if spec.key != "similarAccounts" and spec.key not in _fast_order
        )
        similar_specs = [spec for spec in generation_specs if spec.key == "similarAccounts"]
        await _run_section_batch(fast_specs, sequential=True)
        if section_errors:
            raise section_errors[0]
        await _run_section_batch(similar_specs, sequential=False)

        if section_errors:
            raise section_errors[0]

        for key in reference_fallbacks:
            source_meta_value["referenceDiscovery"][key]["generatedWithoutAI"] = True
            if source_meta_value["referenceDiscovery"][key]["status"] == "complete":
                source_meta_value["referenceDiscovery"][key]["status"] = "partial"

        report: AccountReportPayload | None = None
        if not requested_section_key:
            from ..evidence.research_export import build_research_table

            hot_for_export = section_values.get("hotContents") or []
            if hasattr(hot_for_export, "__iter__") and hot_for_export and not isinstance(
                hot_for_export[0] if hot_for_export else None, dict
            ):
                hot_for_export = [
                    item.model_dump(mode="json", by_alias=True)
                    if hasattr(item, "model_dump")
                    else dict(item)
                    for item in hot_for_export
                ]
            similar_for_export = section_values.get("similarAccounts") or []
            if similar_for_export and not isinstance(
                similar_for_export[0] if similar_for_export else None, dict
            ):
                similar_for_export = [
                    item.model_dump(mode="json", by_alias=True)
                    if hasattr(item, "model_dump")
                    else dict(item)
                    for item in similar_for_export
                ]
            source_meta_value["researchTable"] = build_research_table(
                hot_contents=list(hot_for_export or []),
                topic_reference_pool=list(
                    source_meta_value.get("topicReferencePool") or []
                ),
                similar_accounts=list(similar_for_export or []),
            )
            report = AccountReportPayload.model_validate(
                {**section_values, "sourceMeta": source_meta_value}
            )
            report = _filter_report_candidates(report, evidence)
            report = _merge_hot_content_urls(report, evidence)
            report = _merge_creator_display_data(report, evidence)
            _reject_verbatim_comments(report, evidence)
            report_value = report.model_dump(mode="json", by_alias=True, exclude_none=True)
            report_value["sourceMeta"] = source_meta_value
            report = AccountReportPayload.model_validate(report_value)

        self.store.update_progress(self.workflow_id, progress=95, current_stage="report_persistence")
        user_id = str(account.get("userId") or "")
        account_id = str(account.get("id") or "")
        if requested_section_key:
            persisted = self.store.update_account_report_sections(
                user_id,
                account_id,
                build_section_persistence_payload(
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
                build_report_persistence_payload(report),
            )
        return {
            "reportVersion": report_version(persisted),
            **({"sectionKey": requested_section_key} if requested_section_key else {}),
        }
