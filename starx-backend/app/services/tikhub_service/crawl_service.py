"""将 TikHub 业务结果适配为账号报告使用的 CrawlResult。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerProgressEvent,
    PartialResultCallback,
    ProgressCallback,
)
from app.services.mediaspider.platform_resolver import (
    normalize_keywords,
    normalize_platform,
    resolve_content_platform,
    resolve_creator_platform,
)
from app.services.tikhub_service.models import (
    TikHubAccount,
    TikHubAccountContentsRequest,
    TikHubAccountDetailRequest,
    TikHubContent,
    TikHubContentDetailRequest,
    TikHubPlatform,
    TikHubSearchRequest,
)
from app.services.tikhub_service.provider import TikHubProvider, default_tikhub_provider
from app.services.tikhub_service.content_hydration import (
    hydrate_recent_content_details,
    page_reaches_cutoff,
)

PLATFORM_MAP = {
    "dy": TikHubPlatform.DOUYIN,
    "xhs": TikHubPlatform.XIAOHONGSHU,
    "ks": TikHubPlatform.KUAISHOU,
}

logger = get_logger(__name__)


def _merge_account_details(
    discovered: TikHubAccount,
    hydrated: TikHubAccount,
) -> TikHubAccount:
    """用详情补充搜索结果，同时保留详情响应缺失的公开身份字段。"""

    updates: dict[str, Any] = {}
    for field_name in (
        "accountId",
        "userId",
        "name",
        "avatarUrl",
        "description",
        "profileUrl",
        "ipLocation",
        "province",
        "city",
    ):
        if not str(getattr(hydrated, field_name) or "").strip():
            updates[field_name] = getattr(discovered, field_name)
    for field_name in (
        "followers",
        "follows",
        "contentCount",
        "totalLikes",
        "totalCollects",
    ):
        if int(getattr(hydrated, field_name) or 0) <= 0:
            updates[field_name] = getattr(discovered, field_name)
    if not hydrated.raw:
        updates["raw"] = discovered.raw
    return hydrated.model_copy(update=updates)


@dataclass
class _KeywordCrawlOutcome:
    keyword: str
    contents: list[dict[str, Any]]
    creators: dict[str, dict[str, Any]]
    comments: list[dict[str, Any]]
    source_operations: list[str]
    error: Exception | None = None


async def _emit(callback: ProgressCallback | None, event: CrawlerProgressEvent) -> None:
    if callback is None:
        return
    result = callback(event)
    if hasattr(result, "__await__"):
        await result  # type: ignore[misc]


class TikHubCrawlService:
    """将 TikHub 公开数据适配为旧工作流使用的 CrawlResult。"""

    def __init__(self, provider: TikHubProvider | None = None) -> None:
        self.provider = provider or default_tikhub_provider

    async def crawl_by_keyword(
        self,
        *,
        keywords: str | Sequence[str],
        platform: str,
        on_progress: ProgressCallback | None = None,
        max_notes_count: int = 20,
        enable_comments: bool = False,
        max_comments_count: int = 10,
        reference_discovery: bool = False,
        owner_user_ids: Sequence[str] = (),
        hydrate_douyin_creator_details: bool = False,
        max_creator_details: int = 8,
    ) -> CrawlResult:
        code = normalize_platform(platform)
        social_platform = PLATFORM_MAP[code]
        values = normalize_keywords(keywords)
        limit = max(int(max_notes_count), 1)
        max_comments = max(int(max_comments_count), 1)
        owner_user_ids = [
            str(value)
            for value in owner_user_ids
            if str(value).isdigit()
        ]
        contents: list[dict[str, Any]] = []
        creators: dict[str, dict[str, Any]] = {}
        comments: list[dict[str, Any]] = []
        source_operations: list[str] = []
        discovery_warnings: list[str] = []
        seen: set[str] = set()
        await _emit(on_progress, self._event(code, "search", "run_started", "running", "社媒检索已开始"))
        variants = self._content_search_variants(code) if reference_discovery else [
            ("default", "", "")
        ]
        # max_notes_count 是每个关键词、每个搜索变体的作品配额。
        # 账号报告固定传入 8，正好消费抖音搜索的一个标准首屏。
        variant_limit = limit
        outcomes = await asyncio.gather(
            *(
                self._crawl_one_keyword(
                    code=code,
                    platform=social_platform,
                    keyword=keyword,
                    variants=variants,
                    variant_limit=variant_limit,
                    enable_comments=enable_comments,
                    max_comments=max_comments,
                    on_progress=on_progress,
                )
                for keyword in values
            )
        )
        failed_outcomes = [outcome for outcome in outcomes if outcome.error is not None]
        for outcome in outcomes:
            if outcome.error is not None:
                request_id = getattr(outcome.error, "request_id", None)
                warning = (
                    f"keyword_search_failed:{code}:{outcome.keyword}:"
                    f"{type(outcome.error).__name__}"
                )
                if request_id:
                    warning += f":{request_id}"
                discovery_warnings.append(warning)
            for operation in outcome.source_operations:
                if operation not in source_operations:
                    source_operations.append(operation)
            for item in outcome.contents:
                content_id = str(item.get("content_id") or "")
                if not content_id or content_id in seen:
                    continue
                if reference_discovery and len(contents) >= limit:
                    break
                seen.add(content_id)
                contents.append(item)
            for user_id, creator in outcome.creators.items():
                creators[user_id] = self._merge_creator_records(
                    creators.get(user_id), creator
                )
            comments.extend(outcome.comments)

        if code == "dy" and hydrate_douyin_creator_details:
            hydrated_count = await self._hydrate_douyin_creators(
                creators,
                contents,
                limit=max(int(max_creator_details), 1),
                discovery_warnings=discovery_warnings,
            )
            if hydrated_count and "get_account" not in source_operations:
                source_operations.append("get_account")

        if failed_outcomes and not any(
            outcome.error is None or outcome.contents for outcome in outcomes
        ):
            raise failed_outcomes[0].error  # type: ignore[misc]

        # 账号报告只使用关键词作品搜索返回的作品与作者卡片。
        # reference_discovery 仅保留多排序/内容类型召回，不再触发账号搜索、
        # 账号详情、账号作品列表或平台热点接口，避免为可从作品卡片获得的
        # 作者身份和主页链接重复付费。
        result = CrawlResult(
            platform=code,
            crawl_type="search",
            keywords=values,
            contents=contents,
            comments=comments,
            creators=list(creators.values()),
            content_count=len(contents),
            comment_count=len(comments),
            creator_count=len(creators),
            source_operations=source_operations,
            discovery_warnings=discovery_warnings,
        )
        await _emit(on_progress, self._event(code, "search", "run_completed", "completed", "社媒检索完成", content_count=len(contents), creator_count=len(creators), comment_count=len(comments)))
        return result

    async def _crawl_one_keyword(
        self,
        *,
        code: str,
        platform: TikHubPlatform,
        keyword: str,
        variants: Sequence[tuple[str, str, str]],
        variant_limit: int,
        enable_comments: bool,
        max_comments: int,
        on_progress: ProgressCallback | None,
    ) -> _KeywordCrawlOutcome:
        outcome = _KeywordCrawlOutcome(keyword, [], {}, [], [])
        await _emit(
            on_progress,
            self._event(
                code,
                "search",
                "keyword_started",
                "running",
                "正在检索关键词",
                subject=keyword,
            ),
        )
        seen: set[str] = set()
        try:
            for sort_type, time_filter, note_type in variants:
                cursor = ""
                collected = 0
                while collected < variant_limit:
                    page = await self.provider.search_contents(
                        TikHubSearchRequest(
                            platform=platform,
                            keyword=keyword,
                            cursor=cursor,
                            pageSize=min(20, variant_limit - collected),
                            sortType=sort_type,
                            timeFilter=time_filter,
                            noteType=note_type,
                        )
                    )
                    operation = f"search_contents:{sort_type}"
                    if operation not in outcome.source_operations:
                        outcome.source_operations.append(operation)
                    for content in page.contents:
                        if not content.contentId or content.contentId in seen:
                            continue
                        seen.add(content.contentId)
                        outcome.contents.append(
                            self._content_record(
                                code,
                                content,
                                keyword=keyword,
                                source_operation="search_contents",
                                source_sort=sort_type,
                            )
                        )
                        creator = self._creator_from_content(
                            code,
                            content,
                            keyword=keyword,
                            source_operation="search_contents",
                        )
                        if creator is not None:
                            user_id = creator["user_id"]
                            outcome.creators[user_id] = self._merge_creator_records(
                                outcome.creators.get(user_id), creator
                            )
                        collected += 1
                        if enable_comments:
                            raw_comments, _ = await self.provider.list_comments(
                                platform,
                                content,
                                count=max_comments,
                            )
                            outcome.comments.extend(
                                self._comment_record(code, content.contentId, item)
                                for item in raw_comments[:max_comments]
                            )
                        if collected >= variant_limit:
                            break
                    if not page.hasMore or not page.nextCursor or collected >= variant_limit:
                        break
                    cursor = page.nextCursor
        except Exception as exc:
            outcome.error = exc
            logger.exception(
                "TikHub keyword search failed: platform=%s keyword=%r request_id=%s",
                code,
                keyword,
                getattr(exc, "request_id", None),
            )
            await _emit(
                on_progress,
                self._event(
                    code,
                    "search",
                    "keyword_failed",
                    "failed",
                    "关键词检索失败，继续处理其他关键词",
                    subject=keyword,
                    content_count=len(outcome.contents),
                    creator_count=len(outcome.creators),
                    comment_count=len(outcome.comments),
                ),
            )
            return outcome

        await _emit(
            on_progress,
            self._event(
                code,
                "search",
                "keyword_completed",
                "completed",
                "关键词检索完成",
                subject=keyword,
                content_count=len(outcome.contents),
                creator_count=len(outcome.creators),
                comment_count=len(outcome.comments),
            ),
        )
        return outcome

    @staticmethod
    def _content_search_variants(code: str) -> list[tuple[str, str, str]]:
        if code == "xhs":
            return [
                ("popularity_descending", "一周内", "不限"),
                ("collect_descending", "半年内", "普通笔记"),
                ("comment_descending", "半年内", "不限"),
                ("popularity_descending", "半年内", "视频笔记"),
            ]
        if code == "dy":
            return [("0", "", ""), ("1", "", "")]
        return [("default", "", "")]

    async def _collect_reference_accounts(
        self,
        *,
        code: str,
        platform: TikHubPlatform,
        keywords: Sequence[str],
        creators: dict[str, dict[str, Any]],
        owner_user_ids: Sequence[str],
        source_operations: list[str],
        discovery_warnings: list[str],
    ) -> None:
        recalled: dict[str, tuple[TikHubAccount, set[str]]] = {}
        if code == "dy":
            for owner_user_id in owner_user_ids[:1]:
                try:
                    similar = await self.provider.list_douyin_similar_accounts(
                        owner_user_id
                    )
                except Exception:
                    discovery_warnings.append("douyin_similar_accounts_failed")
                    continue
                if "douyin_similar_accounts" not in source_operations:
                    source_operations.append("douyin_similar_accounts")
                for account in similar:
                    user_id = account.userId or account.accountId
                    if user_id:
                        recalled[user_id] = (account, {"原生相似达人"})
        for keyword in keywords:
            account_query = f"{keyword}{'博主' if code == 'xhs' else '达人'}"
            try:
                page = await self.provider.search_accounts(
                    TikHubSearchRequest(
                        platform=platform,
                        keyword=account_query,
                        pageSize=20,
                    )
                )
            except Exception:
                discovery_warnings.append(f"search_accounts_failed:{code}")
                continue
            if "search_accounts" not in source_operations:
                source_operations.append("search_accounts")
            for account in page.accounts:
                user_id = account.userId or account.accountId
                if not user_id:
                    continue
                if user_id in recalled:
                    recalled[user_id][1].add(keyword)
                else:
                    recalled[user_id] = (account, {keyword})

        async def hydrate(
            user_id: str, account: TikHubAccount, matched: set[str], position: int
        ) -> tuple[str, dict[str, Any]]:
            hydrated = account
            try:
                details = await self.provider.get_account(
                    TikHubAccountDetailRequest(
                        platform=platform,
                        accountId=user_id,
                        userId=user_id,
                    )
                )
                hydrated = _merge_account_details(account, details)
            except Exception:
                discovery_warnings.append(f"get_account_failed:{code}")
                pass
            else:
                if "get_account" not in source_operations:
                    source_operations.append("get_account")
            recent: list[TikHubContent] = []
            if position < 10:
                try:
                    page = await self.provider.list_account_contents(
                        TikHubAccountContentsRequest(
                            platform=platform,
                            accountId=user_id,
                            secUserId=user_id if code == "dy" else "",
                            pageSize=5,
                        )
                    )
                    recent = page.contents[:5]
                except Exception:
                    discovery_warnings.append(f"list_account_contents_failed:{code}")
                    pass
                else:
                    if "list_account_contents" not in source_operations:
                        source_operations.append("list_account_contents")
            record = self._account_record(
                code,
                hydrated,
                matched_queries=sorted(matched),
                recent_contents=recent,
            )
            return user_id, record

        candidates = list(recalled.items())[:15]
        hydrated = await asyncio.gather(
            *(
                hydrate(user_id, account, matched, position)
                for position, (user_id, (account, matched)) in enumerate(candidates)
            )
        )
        for user_id, record in hydrated:
            creators[user_id] = record

    async def _collect_platform_hot_contents(
        self,
        *,
        code: str,
        platform: TikHubPlatform,
        keywords: Sequence[str],
        contents: list[dict[str, Any]],
        creators: dict[str, dict[str, Any]],
        seen: set[str],
        limit: int,
        source_operations: list[str],
        discovery_warnings: list[str],
    ) -> None:
        subtypes = (1002, 1005) if code == "dy" else (None,)
        for subtype in subtypes:
            try:
                candidates = await self.provider.list_hot_contents(
                    platform,
                    subtype=subtype,
                    limit=max(limit // len(subtypes), 1),
                )
            except Exception:
                discovery_warnings.append(
                    f"hot_contents_failed:{code}:{subtype or 'inspiration'}"
                )
                continue
            operation_label = f"hot_contents:{subtype or 'inspiration'}"
            if operation_label not in source_operations:
                source_operations.append(operation_label)
            for content in candidates:
                if not content.contentId or content.contentId in seen:
                    continue
                keyword = self._matched_keyword(content, keywords)
                if not keyword:
                    continue
                seen.add(content.contentId)
                contents.append(
                    self._content_record(
                        code,
                        content,
                        keyword=keyword,
                        source_operation=(
                            f"hot_billboard_{subtype}" if subtype else "hot_inspiration"
                        ),
                        source_sort="hot_feed",
                    )
                )
                creator = self._creator_from_content(code, content)
                if creator is not None:
                    creators.setdefault(creator["user_id"], creator)

    @staticmethod
    def _matched_keyword(content: TikHubContent, keywords: Sequence[str]) -> str:
        text = f"{content.title} {content.description}".lower()
        return next((keyword for keyword in keywords if keyword.lower() in text), "")

    async def crawl_by_creator(
        self,
        *,
        creator_url: str,
        sec_user_id: str = "",
        recent_since: datetime | None = None,
        on_progress: ProgressCallback | None = None,
        on_partial_result: PartialResultCallback | None = None,
        max_notes_count: int = 20,
        max_detail_count: int | None = None,
        enable_comments: bool = False,
        max_comments_count: int = 10,
    ) -> CrawlResult:
        code = resolve_creator_platform(creator_url.strip())
        social_platform = PLATFORM_MAP[code]
        limit = max(int(max_notes_count), 1)
        max_comments = max(int(max_comments_count), 1)
        await _emit(on_progress, self._event(code, "creator", "creator_started", "running", "正在获取账号公开数据"))
        stored_sec_user_id = sec_user_id.strip() if code == "dy" else ""
        account = await self.provider.get_account(
            TikHubAccountDetailRequest(
                platform=social_platform,
                accountId=stored_sec_user_id or creator_url,
                userId=stored_sec_user_id,
                authorUrl="" if stored_sec_user_id else creator_url,
            )
        )
        if on_partial_result is not None:
            partial = on_partial_result(
                CrawlResult(
                    platform=code,
                    crawl_type="creator",
                    creator_url=creator_url,
                    creators=[self._account_record(code, account)],
                    creator_count=1,
                )
            )
            if inspect.isawaitable(partial):
                await partial
        cursor = ""
        contents: list[TikHubContent] = []
        while len(contents) < limit:
            page = await self.provider.list_account_contents(
                TikHubAccountContentsRequest(
                    platform=social_platform,
                    authorUrl="" if stored_sec_user_id else creator_url,
                    secUserId=stored_sec_user_id,
                    cursor=cursor,
                    pageSize=min(20, limit - len(contents)),
                )
            )
            contents.extend(page.contents[: limit - len(contents)])
            if (
                recent_since is not None
                and page_reaches_cutoff(page.contents, recent_since)
            ) or not page.hasMore or not page.nextCursor:
                break
            cursor = page.nextCursor
        if recent_since is not None:
            detail_limit = (
                len(contents)
                if max_detail_count is None
                else min(max(int(max_detail_count), 0), len(contents))
            )
            hydrated = await hydrate_recent_content_details(
                self.provider,
                social_platform,
                contents[:detail_limit],
                recent_since,
            )
            contents = [*hydrated, *contents[detail_limit:]]
        comments: list[dict[str, Any]] = []
        if enable_comments:
            for content in contents:
                raw_comments, _ = await self.provider.list_comments(
                    social_platform, content, count=max_comments
                )
                comments.extend(
                    self._comment_record(code, content.contentId, item)
                    for item in raw_comments[:max_comments]
                )
        raw_contents = [self._content_record(code, item) for item in contents]
        result = CrawlResult(
            platform=code,
            crawl_type="creator",
            creator_url=creator_url,
            contents=raw_contents,
            comments=comments,
            creators=[self._account_record(code, account)],
            content_count=len(raw_contents),
            comment_count=len(comments),
            creator_count=1,
        )
        await _emit(on_progress, self._event(code, "creator", "run_completed", "completed", "社媒账号采集完成", content_count=len(raw_contents), creator_count=1, comment_count=len(comments)))
        return result

    async def crawl_by_detail(
        self,
        *,
        content_url: str,
        on_progress: ProgressCallback | None = None,
        enable_comments: bool = False,
        max_comments_count: int = 10,
    ) -> CrawlResult:
        code = resolve_content_platform(content_url.strip())
        social_platform = PLATFORM_MAP[code]
        await _emit(on_progress, self._event(code, "detail", "detail_started", "running", "正在获取作品公开数据"))
        content = await self.provider.get_content(
            TikHubContentDetailRequest(platform=social_platform, workUrl=content_url)
        )
        comments: list[dict[str, Any]] = []
        if enable_comments:
            max_comments = max(int(max_comments_count), 1)
            raw_comments, _ = await self.provider.list_comments(
                social_platform, content, count=max_comments
            )
            comments = [
                self._comment_record(code, content.contentId, item)
                for item in raw_comments[:max_comments]
            ]
        creator = self._creator_from_content(code, content)
        result = CrawlResult(
            platform=code,
            crawl_type="detail",
            content_url=content_url,
            contents=[self._content_record(code, content)],
            comments=comments,
            creators=[creator] if creator else [],
            content_count=1,
            comment_count=len(comments),
            creator_count=1 if creator else 0,
        )
        await _emit(on_progress, self._event(code, "detail", "run_completed", "completed", "社媒作品采集完成", content_count=1, creator_count=result.creator_count, comment_count=len(comments)))
        return result

    def _account_record(
        self,
        code: str,
        item: TikHubAccount,
        *,
        matched_queries: Sequence[str] = (),
        recent_contents: Sequence[TikHubContent] = (),
    ) -> dict[str, Any]:
        user_id = item.userId or item.accountId
        profile_url = item.profileUrl or next(
            (
                content.authorUrl
                for content in recent_contents
                if content.authorUrl.strip()
            ),
            "",
        )
        interaction_count = sum(
            content.likeCount
            + content.collectCount * 2
            + content.commentCount * 3
            + content.shareCount * 4
            for content in recent_contents
        )
        return {
            "user_id": user_id,
            "sec_user_id": user_id if code == "dy" else "",
            "nickname": item.name,
            "display_name": item.name,
            "profile_url": profile_url,
            "avatar_url": item.avatarUrl,
            "bio": item.description,
            "fans_count": item.followers,
            "following_count": item.follows,
            "works_count": item.contentCount,
            "liked_count": item.totalLikes,
            "numeric_user_id": TikHubCrawlService._numeric_user_id(item.raw),
            "interaction_count": interaction_count or item.totalLikes,
            "hit_content_count": len(recent_contents),
            "representative_contents": [
                content.title or content.contentId for content in recent_contents[:3]
            ],
            "matched_queries": list(matched_queries),
            "source_operations": ["search_accounts", "get_account", "list_account_contents"],
            "evidence_completeness": sum(
                bool(value)
                for value in (
                    user_id,
                    item.name,
                    profile_url,
                    item.description,
                    item.followers,
                    recent_contents,
                )
            ) / 6,
            "source_provider": self.provider.provider_name,
        }

    @staticmethod
    def _numeric_user_id(raw: dict[str, Any]) -> str:
        nodes = [raw]
        while nodes:
            node = nodes.pop(0)
            for key in ("uid", "user_id"):
                value = str(node.get(key) or "")
                if value.isdigit():
                    return value
            nodes.extend(value for value in node.values() if isinstance(value, dict))
        return ""

    @staticmethod
    def _merge_creator_records(
        current: dict[str, Any] | None,
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        if current is None:
            return incoming
        merged = dict(current)
        for field in ("nickname", "display_name", "profile_url", "avatar_url"):
            if not str(merged.get(field) or "").strip():
                merged[field] = incoming.get(field, "")
        for field in ("fans_count", "works_count", "liked_count"):
            merged[field] = max(
                int(merged.get(field) or 0),
                int(incoming.get(field) or 0),
            )
        for field in ("matched_queries", "source_operations"):
            merged[field] = list(
                dict.fromkeys(
                    [
                        *list(merged.get(field) or []),
                        *list(incoming.get(field) or []),
                    ]
                )
            )
        merged["evidence_completeness"] = max(
            float(merged.get("evidence_completeness") or 0),
            float(incoming.get("evidence_completeness") or 0),
        )
        return merged

    async def _hydrate_douyin_creators(
        self,
        creators: dict[str, dict[str, Any]],
        contents: list[dict[str, Any]],
        *,
        limit: int,
        discovery_warnings: list[str],
    ) -> int:
        """只为作品命中最多的抖音候选补充一次账号详情。"""

        hit_counts: dict[str, int] = {}
        for content in contents:
            author_id = str(content.get("author_id") or "").strip()
            if author_id in creators:
                hit_counts[author_id] = hit_counts.get(author_id, 0) + 1
        candidate_ids = sorted(
            creators,
            key=lambda user_id: hit_counts.get(user_id, 0),
            reverse=True,
        )[:limit]

        async def hydrate(user_id: str) -> tuple[str, dict[str, Any] | None]:
            try:
                account = await self.provider.get_account(
                    TikHubAccountDetailRequest(
                        platform=TikHubPlatform.DOUYIN,
                        accountId=user_id,
                        userId=user_id,
                    )
                )
            except Exception as exc:
                request_id = getattr(exc, "request_id", None)
                warning = f"get_account_failed:dy:{type(exc).__name__}"
                if request_id:
                    warning += f":{request_id}"
                discovery_warnings.append(warning)
                return user_id, None
            current = creators[user_id]
            hydrated = self._account_record(
                "dy",
                account,
                matched_queries=list(current.get("matched_queries") or []),
            )
            hydrated["source_operations"] = ["get_account"]
            return user_id, hydrated

        results = await asyncio.gather(*(hydrate(user_id) for user_id in candidate_ids))
        hydrated_count = 0
        for user_id, hydrated in results:
            if hydrated is None:
                continue
            creators[user_id] = self._merge_creator_records(
                creators[user_id], hydrated
            )
            hydrated_count += 1
        return hydrated_count

    def _creator_from_content(
        self,
        code: str,
        item: TikHubContent,
        *,
        keyword: str = "",
        source_operation: str = "",
    ) -> dict[str, Any] | None:
        if not item.authorId:
            return None
        return {
            "user_id": item.authorId,
            "sec_user_id": item.authorId if code == "dy" else "",
            "nickname": item.authorName,
            "display_name": item.authorName,
            "profile_url": item.authorUrl,
            "avatar_url": item.authorAvatarUrl,
            "fans_count": item.authorFollowers,
            "works_count": item.authorContentCount,
            "liked_count": item.authorTotalLikes,
            "matched_queries": [keyword] if keyword else [],
            "source_operations": [source_operation] if source_operation else [],
            "evidence_completeness": sum(
                bool(value)
                for value in (item.authorId, item.authorName, item.authorUrl)
            )
            / 3,
            "source_provider": self.provider.provider_name,
        }

    def _content_record(
        self,
        code: str,
        item: TikHubContent,
        *,
        keyword: str = "",
        source_operation: str = "",
        source_sort: str = "",
    ) -> dict[str, Any]:
        id_field = {"dy": "aweme_id", "xhs": "note_id", "ks": "video_id"}[code]
        url_field = {"dy": "aweme_url", "xhs": "note_url", "ks": "video_url"}[code]
        return {
            id_field: item.contentId,
            url_field: item.contentUrl,
            "content_id": item.contentId,
            "public_url": item.contentUrl,
            "title": item.title,
            "desc": item.description,
            "cover_url": item.coverUrl,
            "author_id": item.authorId,
            "nickname": item.authorName,
            "display_name": item.authorName,
            "profile_url": item.authorUrl,
            "create_time": item.publishedAt,
            "liked_count": item.likeCount,
            "comment_count": item.commentCount,
            "share_count": item.shareCount,
            "collected_count": item.collectCount,
            "view_count": item.readCount,
            "content_type": item.contentType,
            "source_keyword": keyword,
            "source_operation": source_operation,
            "source_sort": source_sort,
            "source_provider": self.provider.provider_name,
        }

    def _comment_record(
        self, code: str, content_id: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        content = raw.get("content") or raw.get("text") or raw.get("comment") or ""
        return {
            "content_id": content_id,
            "parent_content_id": content_id,
            "comment_id": str(raw.get("cid") or raw.get("comment_id") or raw.get("id") or ""),
            "content": str(content),
            "like_count": raw.get("digg_count") or raw.get("like_count") or 0,
            "source_provider": self.provider.provider_name,
        }

    @staticmethod
    def _event(
        platform: str,
        crawl_type: str,
        action: str,
        status: str,
        message: str,
        *,
        subject: str = "",
        content_count: int = 0,
        creator_count: int = 0,
        comment_count: int = 0,
    ) -> CrawlerProgressEvent:
        return CrawlerProgressEvent(
            platform=platform,
            crawlType=crawl_type,
            action=action,
            status=status,
            message=message,
            subject=subject,
            contentCount=content_count,
            creatorCount=creator_count,
            commentCount=comment_count,
        )
