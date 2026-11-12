from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.services.extract_service.platforms.base import (
    clean_text,
    extract_json_assignment,
)
from app.services.extract_service.platforms.rednote import rednote_best_image_url

from .base import (
    BaseProfileExtractor,
    ExtractError,
    ExtractedProfile,
    ExtractedProfileWork,
    count_value,
    display_count,
)


class RednoteProfileExtractor(BaseProfileExtractor):
    platform = "rednote"

    def extract(self) -> ExtractedProfile:
        response = self.fetch()
        return self.parse(response.text, response.url)

    def parse(self, html: str, resolved_url: str) -> ExtractedProfile:
        state = extract_json_assignment(html, "window.__INITIAL_STATE__")
        user_state = state.get("user") if isinstance(state.get("user"), dict) else {}
        page = (
            user_state.get("userPageData")
            if isinstance(user_state.get("userPageData"), dict)
            else {}
        )
        basic = page.get("basicInfo") if isinstance(page.get("basicInfo"), dict) else {}
        if not basic:
            raise ExtractError("小红书公开主页未返回可解析的博主信息")

        interactions = _interactions(page.get("interactions"))
        labels = {
            "following": interactions.get("follows", ""),
            "followers": interactions.get("fans", ""),
            "liked": interactions.get("interaction", ""),
        }
        works_count_label = display_count(
            _first(page, "notesCount", "noteCount", "worksCount")
            or _first(basic, "notesCount", "noteCount", "worksCount")
        )
        if works_count_label:
            labels["worksCount"] = works_count_label
        return ExtractedProfile(
            platform=self.platform,
            url=self.url,
            resolved_url=resolved_url,
            name=clean_text(_first(basic, "nickname", "nickName", "name")) or "",
            account_id=str(_first(basic, "redId", "userId", "id") or ""),
            avatar=str(_first(basic, "imageb", "images", "avatar") or ""),
            description=clean_text(_first(basic, "desc", "description")) or "",
            following=count_value(labels["following"]),
            followers=count_value(labels["followers"]),
            liked=count_value(labels["liked"]),
            works_count=count_value(works_count_label),
            metric_labels={key: value for key, value in labels.items() if value},
            works=_works(user_state.get("notes"), self.limit),
            raw={"source": "INITIAL_STATE"},
        )


def _interactions(value: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip()
        if kind:
            result[kind] = display_count(item.get("count"))
    return result


def _works(value: Any, limit: int) -> list[ExtractedProfileWork]:
    result: list[ExtractedProfileWork] = []
    seen: set[str] = set()
    for item in _flatten(value):
        card = item.get("noteCard") if isinstance(item.get("noteCard"), dict) else item
        note_id = str(
            card.get("noteId") or card.get("id") or item.get("id") or ""
        ).strip()
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        token = str(card.get("xsecToken") or item.get("xsecToken") or "").strip()
        query = (
            urlencode({"xsec_token": token, "xsec_source": "pc_user"})
            if token
            else ""
        )
        cover = card.get("cover") if isinstance(card.get("cover"), dict) else {}
        result.append(
            ExtractedProfileWork(
                id=note_id,
                url=f"https://www.xiaohongshu.com/explore/{note_id}"
                + (f"?{query}" if query else ""),
                title=clean_text(card.get("displayTitle") or card.get("title")) or "",
                cover=rednote_best_image_url(cover) or "",
                published_at=str(card.get("time") or card.get("createTime") or ""),
            )
        )
        if len(result) >= limit:
            break
    return result


def _flatten(value: Any):
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _flatten(item)


def _first(item: dict[str, Any], *keys: str) -> Any:
    return next((item.get(key) for key in keys if item.get(key) is not None), None)
