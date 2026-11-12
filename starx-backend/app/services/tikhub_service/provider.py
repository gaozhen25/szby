"""StarX 业务使用的 TikHub 类型化 SDK 能力。"""

from __future__ import annotations

from collections.abc import Awaitable
import json
import logging
from typing import Any, TypeVar

from tikhub import (
    AsyncTikHub,
    TikHubAuthError,
    TikHubBadRequestError,
    TikHubConfigError,
    TikHubError,
    TikHubHTTPError,
    TikHubPermissionError,
    TikHubRateLimitError,
)

from app.services.tikhub_service.errors import (
    InvalidTikHubRequestError,
    TikHubBusinessBudgetError,
    TikHubBusinessConfigError,
    TikHubBusinessRateLimitError,
    TikHubBusinessRequestError,
    UnsupportedTikHubOperationError,
)
from app.services.tikhub_service.models import (
    TikHubAccount,
    TikHubAccountContentsRequest,
    TikHubAccountDetailRequest,
    TikHubAccountPage,
    TikHubAiContentSearchRequest,
    TikHubContent,
    TikHubContentDetailRequest,
    TikHubContentPage,
    TikHubPlatform,
    TikHubSearchRequest,
)
from app.services.tikhub_service.normalizers import normalize_account, normalize_content
from app.services.tikhub_service.response import (
    decode_cursor,
    encode_cursor,
    first_item,
    item_list,
    mapping,
    nested_string,
    page_state,
    pagination_state,
)
from app.services.tikhub_service.runtime import default_tikhub_runtime
from app.services.mediaspider.platform_resolver import (
    extract_douyin_sec_user_id,
    extract_xiaohongshu_user_id,
)

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)
_MAX_LOG_BODY_CHARS = 4000


class TikHubProvider:
    provider_name = "tikhub"

    def __init__(self, sdk: AsyncTikHub | None = None) -> None:
        self._sdk = sdk

    @property
    def sdk(self) -> AsyncTikHub:
        return self._sdk or default_tikhub_runtime.client

    async def _execute(self, request: Awaitable[ResultT]) -> ResultT:
        try:
            return await request
        except TikHubBadRequestError as exc:
            _log_tikhub_http_error(exc)
            raise InvalidTikHubRequestError(
                "TikHub rejected the request parameters"
                + (f" (request_id={exc.request_id})" if exc.request_id else ""),
                request_id=exc.request_id,
            ) from exc
        except (TikHubAuthError, TikHubPermissionError, TikHubConfigError) as exc:
            if isinstance(exc, TikHubHTTPError):
                _log_tikhub_http_error(exc)
            raise TikHubBusinessConfigError(
                "TikHub credentials are invalid or lack permission"
            ) from exc
        except TikHubRateLimitError as exc:
            _log_tikhub_http_error(exc)
            raise TikHubBusinessRateLimitError(
                "TikHub request rate limit exceeded",
                retry_after=exc.retry_after,
                request_id=exc.request_id,
            ) from exc
        except TikHubHTTPError as exc:
            _log_tikhub_http_error(exc)
            if exc.status_code == 402:
                raise TikHubBusinessBudgetError(
                    "TikHub balance or request budget is exhausted",
                    request_id=exc.request_id,
                ) from exc
            raise TikHubBusinessRequestError(
                "TikHub upstream request failed",
                request_id=exc.request_id,
            ) from exc
        except TikHubError as exc:
            raise TikHubBusinessRequestError("TikHub SDK request failed") from exc

    async def search_accounts(self, request: TikHubSearchRequest) -> TikHubAccountPage:
        state = decode_cursor(request.cursor, request.platform.value)
        if request.platform == TikHubPlatform.DOUYIN:
            raw = await self._execute(
                self.sdk.douyin_search.fetch_user_search_v2(
                    keyword=request.keyword,
                    cursor=state.get("cursor", request.offset),
                )
            )
            keys = ("user_list", "users", "data", "list")
        elif request.platform == TikHubPlatform.XIAOHONGSHU:
            page = int(state.get("page") or request.offset // request.pageSize + 1)
            raw = await self._execute(
                self.sdk.xiaohongshu_app_v2.search_users(
                    keyword=request.keyword,
                    page=page,
                    search_id=state.get("search_id"),
                    source="explore_feed",
                )
            )
            keys = ("users", "items", "data", "list")
        else:
            page = str(state.get("page") or request.offset // request.pageSize + 1)
            raw = await self._execute(
                self.sdk.kuaishou_app.search_user_v2(
                    keyword=request.keyword,
                    page=page,
                )
            )
            keys = ("users", "items", "data", "list")
        data = mapping(raw)
        items = item_list(data, *keys)
        upstream_state = pagination_state(data)
        has_more, _ = page_state(data)
        return TikHubAccountPage(
            platform=request.platform,
            total=int(data.get("total") or len(items)),
            hasMore=has_more,
            offset=request.offset,
            nextCursor=self._next_search_cursor(
                request, state, has_more, upstream_state
            ),
            accounts=[normalize_account(request.platform, item) for item in items],
        )

    async def search_contents(self, request: TikHubSearchRequest) -> TikHubContentPage:
        state = decode_cursor(request.cursor, request.platform.value)
        if request.platform == TikHubPlatform.DOUYIN:
            raw = await self._execute(
                self.sdk.douyin_search.fetch_video_search_v2(
                    keyword=request.keyword,
                    cursor=state.get("cursor", request.offset),
                    sort_type=(
                        None if request.sortType == "default" else request.sortType
                    ),
                    search_id=state.get("search_id"),
                    backtrace=state.get("backtrace"),
                )
            )
            keys = ("business_data", "aweme_list", "items", "data", "list")
        elif request.platform == TikHubPlatform.XIAOHONGSHU:
            page = int(state.get("page") or request.offset // request.pageSize + 1)
            raw = await self._execute(
                self.sdk.xiaohongshu_app_v2.search_notes(
                    keyword=request.keyword,
                    page=page,
                    sort_type=(
                        None if request.sortType == "default" else request.sortType
                    ),
                    note_type=request.noteType or None,
                    time_filter=request.timeFilter or None,
                    search_id=state.get("search_id"),
                    search_session_id=state.get("search_session_id"),
                    source="explore_feed",
                )
            )
            keys = ("items", "notes", "data", "list")
        else:
            page = str(state.get("page") or request.offset // request.pageSize + 1)
            raw = await self._execute(
                self.sdk.kuaishou_app.search_video_v2(
                    keyword=request.keyword,
                    page=page,
                )
            )
            keys = ("feeds", "photos", "items", "data", "list")
        data = mapping(raw)
        items = item_list(data, *keys)
        upstream_state = pagination_state(data)
        has_more, _ = page_state(data)
        return TikHubContentPage(
            platform=request.platform,
            total=int(data.get("total") or len(items)),
            hasMore=has_more,
            offset=request.offset,
            pageNum=int(state.get("page") or request.offset // request.pageSize + 1),
            pageSize=request.pageSize,
            nextCursor=self._next_search_cursor(
                request, state, has_more, upstream_state
            ),
            contents=[normalize_content(request.platform, item) for item in items],
        )

    async def list_hot_contents(
        self,
        platform: TikHubPlatform,
        *,
        subtype: int | None = None,
        limit: int = 20,
    ) -> list[TikHubContent]:
        if platform == TikHubPlatform.XIAOHONGSHU:
            raw = await self._execute(
                self.sdk.xiaohongshu_app_v2.get_creator_hot_inspiration_feed(
                    cursor=None
                )
            )
            keys = ("items", "notes", "feeds", "data", "list")
        elif platform == TikHubPlatform.DOUYIN:
            raw = await self._execute(
                self.sdk.douyin_billboard.fetch_hot_total_video_list(
                    page=1,
                    page_size=min(max(limit, 1), 50),
                    date_window=7,
                    sub_type=subtype or 1002,
                    tags=None,
                )
            )
            keys = ("aweme_list", "items", "videos", "data", "list")
        else:
            return []
        data = mapping(raw)
        return [
            normalize_content(platform, item)
            for item in item_list(data, *keys)[:limit]
        ]

    async def list_douyin_similar_accounts(self, user_id: str) -> list[TikHubAccount]:
        if not user_id.isdigit():
            return []
        raw = await self._execute(
            self.sdk.douyin_index.fetch_daren_similar_users(user_id=user_id)
        )
        data = mapping(raw)
        return [
            normalize_account(TikHubPlatform.DOUYIN, item)
            for item in item_list(data, "users", "user_list", "items", "data", "list")
        ]

    async def get_account(self, request: TikHubAccountDetailRequest) -> TikHubAccount:
        identity = request.authorUrl or request.userId or request.accountId
        if request.platform == TikHubPlatform.DOUYIN:
            if request.accountId and not request.authorUrl and not request.userId:
                # accountId 在统一模型中表示平台展示号。抖音首次绑定必须用
                # unique_id 专用接口，不能把纯数字抖音号误当成 sec_user_id，
                # 也不应先走关键词搜索。
                data = mapping(
                    await self._execute(
                        self.sdk.douyin_web.handler_user_profile_v2(
                            unique_id=request.accountId
                        )
                    )
                )
            else:
                sec_user_id = extract_douyin_sec_user_id(identity)
                if identity.startswith("http"):
                    if not sec_user_id:
                        resolved = mapping(
                            await self._execute(
                                self.sdk.douyin_web.get_sec_user_id(url=identity)
                            )
                        )
                        sec_user_id = str(
                            resolved.get("sec_user_id")
                            or resolved.get("sec_uid")
                            or resolved.get("data")
                            or ""
                        )
                else:
                    sec_user_id = identity
                # Web V4 除公开账号基础资料外，还返回年龄、直播用户、粉丝团、
                # 粉丝牌及商业化相关结构。保留整个 data 对象给 raw，避免在统一
                # 账号模型只提取基础字段时丢失后续博主画像分析所需的 live_user。
                data = mapping(
                    await self._execute(
                        self.sdk.douyin_web.handler_user_profile_v4(
                            sec_user_id=sec_user_id
                        )
                    )
                )
            if data.get("status_code") not in (None, 0, "0"):
                raise TikHubBusinessRequestError(
                    "TikHub Douyin Web returned an unsuccessful profile response"
                )
        elif request.platform == TikHubPlatform.XIAOHONGSHU:
            user_id = extract_xiaohongshu_user_id(identity)
            params = (
                {"user_id": user_id}
                if user_id
                else (
                    {"share_text": identity}
                    if identity.startswith("http")
                    else {"user_id": identity}
                )
            )
            data = first_item(
                mapping(
                    await self._execute(
                        self.sdk.xiaohongshu_app_v2.get_user_info(**params)
                    )
                ),
                "user",
                "user_info",
            )
        else:
            user_id = identity
            if identity.startswith("http"):
                resolved = mapping(
                    await self._execute(
                        self.sdk.kuaishou_web.fetch_get_user_id(
                            share_link=identity
                        )
                    )
                )
                user_id = str(
                    resolved.get("user_id")
                    or resolved.get("eid")
                    or resolved.get("data")
                    or ""
                )
            data = first_item(
                mapping(
                    await self._execute(
                        self.sdk.kuaishou_app.fetch_one_user_v2(user_id=user_id)
                    )
                ),
                "user",
                "user_info",
            )
        return normalize_account(request.platform, data)

    async def get_content(self, request: TikHubContentDetailRequest) -> TikHubContent:
        identity = request.workUrl or request.workId
        if request.platform == TikHubPlatform.DOUYIN:
            call = (
                self.sdk.douyin_app_v3.fetch_one_video_by_share_url(
                    share_url=request.workUrl
                )
                if request.workUrl
                else self.sdk.douyin_app_v3.fetch_one_video_v3(
                    aweme_id=request.workId
                )
            )
            data = first_item(mapping(await self._execute(call)), "aweme_detail", "aweme", "item")
        elif request.platform == TikHubPlatform.XIAOHONGSHU:
            params = (
                {"share_text": identity}
                if request.workUrl
                else {"note_id": identity}
            )
            operations = (
                # App V2 的图文详情实际可返回视频笔记的基础元数据、互动数和
                # xsec_token；视频详情对部分视频会 success=true 但 data 为空。
                self.sdk.xiaohongshu_app_v2.get_image_note_detail,
                self.sdk.xiaohongshu_app_v2.get_video_note_detail,
            )
            data = {}
            for operation in operations:
                try:
                    mapped = mapping(await self._execute(operation(**params)))
                except InvalidTikHubRequestError:
                    continue
                detail_items = item_list(mapped, "note_list", "notes")
                candidate = (
                    detail_items[0]
                    if detail_items
                    else first_item(mapped, "note", "note_card", "item")
                )
                if any(candidate.get(key) for key in ("id", "note_id")):
                    data = candidate
                    break
        else:
            call = (
                self.sdk.kuaishou_app.fetch_one_video_by_url(
                    share_text=request.workUrl
                )
                if request.workUrl
                else self.sdk.kuaishou_app.fetch_one_video(photo_id=request.workId)
            )
            data = first_item(mapping(await self._execute(call)), "photo", "item")
        return normalize_content(request.platform, data)

    async def get_douyin_content_statistics(
        self,
        content_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        """批量补充抖音公开作品统计；单批最多五十条。"""

        normalized_ids = list(
            dict.fromkeys(str(value).strip() for value in content_ids if str(value).strip())
        )[:50]
        if not normalized_ids:
            return {}
        raw = await self._execute(
            self.sdk.douyin_app_v3.fetch_multi_video_statistics(
                aweme_ids=",".join(normalized_ids)
            )
        )
        data = mapping(raw)
        items = item_list(
            data,
            "statistics_list",
            "statistics",
            "aweme_list",
            "items",
            "data",
            "list",
        )
        result: dict[str, dict[str, int]] = {}
        for item in items:
            content_id = str(
                item.get("aweme_id")
                or item.get("awemeId")
                or item.get("id")
                or ""
            ).strip()
            if not content_id:
                continue

            def integer(*keys: str) -> int:
                for key in keys:
                    value = item.get(key)
                    if value not in (None, ""):
                        try:
                            return max(int(value), 0)
                        except (TypeError, ValueError):
                            return 0
                return 0

            result[content_id] = {
                "views": integer("play_count", "playCount"),
                "likes": integer("digg_count", "like_count", "diggCount"),
                "shares": integer("share_count", "shareCount"),
                "downloads": integer("download_count", "downloadCount"),
            }
        return result

    async def list_account_contents(
        self,
        request: TikHubAccountContentsRequest,
    ) -> TikHubContentPage:
        state = decode_cursor(request.cursor, request.platform.value)
        identity = request.authorUrl or request.secUserId or request.accountId
        if request.platform == TikHubPlatform.DOUYIN:
            sec_user_id = extract_douyin_sec_user_id(identity)
            if identity.startswith("http"):
                if not sec_user_id:
                    resolved = mapping(
                        await self._execute(
                            self.sdk.douyin_web.get_sec_user_id(url=identity)
                        )
                    )
                    sec_user_id = str(
                        resolved.get("sec_user_id")
                        or resolved.get("sec_uid")
                        or resolved.get("data")
                        or ""
                    )
            else:
                sec_user_id = identity
            try:
                max_cursor = int(state.get("cursor", request.offset))
            except (TypeError, ValueError):
                max_cursor = request.offset
            raw = await self._execute(
                self.sdk.douyin_app_v3.fetch_user_post_videos(
                    sec_user_id=sec_user_id,
                    max_cursor=max_cursor,
                    count=request.pageSize,
                    sort_type=0,
                )
            )
            keys = ("aweme_list", "items", "data", "list")
        elif request.platform == TikHubPlatform.XIAOHONGSHU:
            params: dict[str, Any] = {"cursor": state.get("cursor")}
            user_id = extract_xiaohongshu_user_id(identity)
            if user_id:
                params["user_id"] = user_id
            else:
                params[
                    "share_text" if identity.startswith("http") else "user_id"
                ] = identity
            raw = await self._execute(
                self.sdk.xiaohongshu_app_v2.get_user_posted_notes(**params)
            )
            keys = ("notes", "items", "data", "list")
        else:
            user_id = identity
            if identity.startswith("http"):
                resolved = mapping(
                    await self._execute(
                        self.sdk.kuaishou_web.fetch_get_user_id(
                            share_link=identity
                        )
                    )
                )
                user_id = str(
                    resolved.get("user_id")
                    or resolved.get("eid")
                    or resolved.get("data")
                    or ""
                )
            raw = await self._execute(
                self.sdk.kuaishou_app.fetch_user_post_v2(
                    user_id=user_id,
                    pcursor=state.get("cursor"),
                )
            )
            keys = ("feeds", "photos", "items", "data", "list")
        data = mapping(raw)
        items = item_list(data, *keys)
        author_profile_url = (
            nested_string(data, "share_link")
            if request.platform == TikHubPlatform.XIAOHONGSHU
            else ""
        )
        has_more, upstream_cursor = page_state(data)
        if (
            request.platform == TikHubPlatform.XIAOHONGSHU
            and has_more
            and upstream_cursor is None
            and items
        ):
            upstream_cursor = items[-1].get("cursor") or items[-1].get("id")
        next_cursor = (
            encode_cursor(request.platform.value, cursor=upstream_cursor)
            if has_more and upstream_cursor is not None
            else ""
        )
        return TikHubContentPage(
            platform=request.platform,
            total=int(data.get("total") or len(items)),
            hasMore=has_more,
            offset=request.offset,
            pageSize=request.pageSize,
            nextCursor=next_cursor,
            contents=[
                normalize_content(
                    request.platform,
                    item,
                    author_profile_url=author_profile_url,
                )
                for item in items
            ],
        )

    async def list_comments(
        self,
        platform: TikHubPlatform,
        content: TikHubContent,
        *,
        cursor: str = "",
        count: int = 20,
    ) -> tuple[list[dict[str, Any]], str]:
        state = decode_cursor(cursor, platform.value)
        if platform == TikHubPlatform.DOUYIN:
            raw = await self._execute(
                self.sdk.douyin_app_v3.fetch_video_comments(
                    aweme_id=content.contentId,
                    cursor=state.get("cursor"),
                    count=count,
                )
            )
        elif platform == TikHubPlatform.XIAOHONGSHU:
            raw = await self._execute(
                self.sdk.xiaohongshu_app_v2.get_note_comments(
                    note_id=content.contentId,
                    cursor=state.get("cursor"),
                )
            )
        else:
            raw = await self._execute(
                self.sdk.kuaishou_app.fetch_one_video_comment(
                    photo_id=content.contentId,
                    pcursor=state.get("cursor"),
                )
            )
        data = mapping(raw)
        comments = item_list(data, "comments", "items", "data", "list")
        has_more, upstream_cursor = page_state(data)
        next_cursor = (
            encode_cursor(platform.value, cursor=upstream_cursor)
            if has_more and upstream_cursor is not None
            else ""
        )
        return comments, next_cursor

    async def search_ai_contents(
        self,
        request: TikHubAiContentSearchRequest,
    ) -> TikHubContentPage:
        raise UnsupportedTikHubOperationError(
            "TikHub standard search does not provide a verified equivalent AI-content classifier"
        )

    @staticmethod
    def _next_search_cursor(
        request: TikHubSearchRequest,
        state: dict[str, Any],
        has_more: bool,
        upstream_state: dict[str, Any],
    ) -> str:
        if not has_more:
            return ""
        if request.platform == TikHubPlatform.DOUYIN:
            return encode_cursor(
                request.platform.value,
                cursor=upstream_state.get("cursor", state.get("cursor")),
                search_id=upstream_state.get("search_id", state.get("search_id")),
                backtrace=upstream_state.get("backtrace", state.get("backtrace")),
            )
        page = int(state.get("page") or request.offset // request.pageSize + 1) + 1
        return encode_cursor(
            request.platform.value,
            page=page,
            cursor=upstream_state.get("cursor"),
            search_id=upstream_state.get("search_id", state.get("search_id")),
            search_session_id=upstream_state.get(
                "search_session_id", state.get("search_session_id")
            ),
        )


default_tikhub_provider = TikHubProvider()


def _log_tikhub_http_error(exc: TikHubHTTPError) -> None:
    """记录 TikHub 失败响应，保留排查所需的上游 body。"""

    logger.error(
        "TikHub interface failed status_code=%s method=%s url=%s params=%s "
        "request_id=%s response_body=%s",
        exc.status_code,
        exc.method,
        exc.url,
        _compact_log_value(exc.params),
        exc.request_id,
        _compact_log_value(exc.response_body),
    )


def _compact_log_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    if len(text) <= _MAX_LOG_BODY_CHARS:
        return text
    return text[:_MAX_LOG_BODY_CHARS] + "...<truncated>"
