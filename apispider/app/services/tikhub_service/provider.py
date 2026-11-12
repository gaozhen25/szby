"""StarX 业务使用的 TikHub 类型化 SDK 能力。"""

from __future__ import annotations

from collections.abc import Awaitable
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
    page_state,
    pagination_state,
)
from app.services.tikhub_service.runtime import default_tikhub_runtime

ResultT = TypeVar("ResultT")


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
            raise InvalidTikHubRequestError(
                "TikHub rejected the request parameters"
                + (f" (request_id={exc.request_id})" if exc.request_id else ""),
                request_id=exc.request_id,
            ) from exc
        except (TikHubAuthError, TikHubPermissionError, TikHubConfigError) as exc:
            raise TikHubBusinessConfigError(
                "TikHub credentials are invalid or lack permission"
            ) from exc
        except TikHubRateLimitError as exc:
            raise TikHubBusinessRateLimitError(
                "TikHub request rate limit exceeded",
                retry_after=exc.retry_after,
                request_id=exc.request_id,
            ) from exc
        except TikHubHTTPError as exc:
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
            sec_user_id = identity
            if identity.startswith("http"):
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
            raw = await self._execute(
                self.sdk.douyin_app_v3.handler_user_profile(
                    sec_user_id=sec_user_id
                )
            )
            data = first_item(mapping(raw), "user", "user_info")
        elif request.platform == TikHubPlatform.XIAOHONGSHU:
            params = (
                {"share_text": identity}
                if identity.startswith("http")
                else {"user_id": identity}
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
            content_type = request.contentType.strip().lower()
            try:
                call = (
                    self.sdk.xiaohongshu_app_v2.get_video_note_detail(**params)
                    if content_type in {"video", "视频", "视频笔记"}
                    else self.sdk.xiaohongshu_app_v2.get_image_note_detail(**params)
                )
                raw = await self._execute(call)
            except InvalidTikHubRequestError:
                if content_type:
                    raise
                raw = await self._execute(
                    self.sdk.xiaohongshu_app_v2.get_video_note_detail(**params)
                )
            data = first_item(mapping(raw), "note", "note_card", "item")
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

    async def list_account_contents(
        self,
        request: TikHubAccountContentsRequest,
    ) -> TikHubContentPage:
        state = decode_cursor(request.cursor, request.platform.value)
        identity = request.authorUrl or request.secUserId or request.accountId
        if request.platform == TikHubPlatform.DOUYIN:
            sec_user_id = identity
            if identity.startswith("http"):
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
            raw = await self._execute(
                self.sdk.douyin_app_v3.fetch_user_post_videos(
                    sec_user_id=sec_user_id,
                    max_cursor=state.get("cursor", request.offset),
                    count=request.pageSize,
                )
            )
            keys = ("aweme_list", "items", "data", "list")
        elif request.platform == TikHubPlatform.XIAOHONGSHU:
            params: dict[str, Any] = {"cursor": state.get("cursor")}
            params["share_text" if identity.startswith("http") else "user_id"] = identity
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
        has_more, upstream_cursor = page_state(data)
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
            contents=[normalize_content(request.platform, item) for item in items],
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
