"""将 TikHub 业务结果适配为账号报告使用的 CrawlResult。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerProgressEvent,
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

PLATFORM_MAP = {
    "dy": TikHubPlatform.DOUYIN,
    "xhs": TikHubPlatform.XIAOHONGSHU,
    "ks": TikHubPlatform.KUAISHOU,
}

logger = get_logger(__name__)


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
        variant_limit = (
            max(1, limit // max(len(values) * len(variants), 1))
            if reference_discovery
            else limit
        )
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
            creators.update(outcome.creators)
            comments.extend(outcome.comments)

        if failed_outcomes and not any(
            outcome.error is None or outcome.contents for outcome in outcomes
        ):
            raise failed_outcomes[0].error  # type: ignore[misc]

        if reference_discovery:
            await self._collect_reference_accounts(
                code=code,
                platform=social_platform,
                keywords=values,
                creators=creators,
                owner_user_ids=owner_user_ids,
                source_operations=source_operations,
                discovery_warnings=discovery_warnings,
            )
            await self._collect_platform_hot_contents(
                code=code,
                platform=social_platform,
                keywords=values,
                contents=contents,
                creators=creators,
                seen=seen,
                limit=min(limit, 20),
                source_operations=source_operations,
                discovery_warnings=discovery_warnings,
            )
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
                        creator = self._creator_from_content(code, content)
                        if creator is not None:
                            outcome.creators.setdefault(creator["user_id"], creator)
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
                hydrated = await self.provider.get_account(
                    TikHubAccountDetailRequest(
                        platform=platform,
                        accountId=user_id,
                        userId=user_id,
                    )
                )
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
        on_progress: ProgressCallback | None = None,
        max_notes_count: int = 20,
        enable_comments: bool = False,
        max_comments_count: int = 10,
    ) -> CrawlResult:
        code = resolve_creator_platform(creator_url.strip())
        social_platform = PLATFORM_MAP[code]
        limit = max(int(max_notes_count), 1)
        max_comments = max(int(max_comments_count), 1)
        await _emit(on_progress, self._event(code, "creator", "creator_started", "running", "正在获取账号公开数据"))
        account = await self.provider.get_account(
            TikHubAccountDetailRequest(platform=social_platform, accountId=creator_url, authorUrl=creator_url)
        )
        cursor = ""
        contents: list[TikHubContent] = []
        while len(contents) < limit:
            page = await self.provider.list_account_contents(
                TikHubAccountContentsRequest(
                    platform=social_platform,
                    authorUrl=creator_url,
                    cursor=cursor,
                    pageSize=min(20, limit - len(contents)),
                )
            )
            contents.extend(page.contents[: limit - len(contents)])
            if not page.hasMore or not page.nextCursor:
                break
            cursor = page.nextCursor
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
            "profile_url": item.profileUrl,
            "avatar": item.avatarUrl,
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
                    item.profileUrl,
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

    def _creator_from_content(self, code: str, item: TikHubContent) -> dict[str, Any] | None:
        if not item.authorId:
            return None
        return {
            "user_id": item.authorId,
            "sec_user_id": item.authorId if code == "dy" else "",
            "nickname": item.authorName,
            "display_name": item.authorName,
            "profile_url": item.authorUrl,
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
