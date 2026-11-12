from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

from app.services.extract_service.platforms.base import (
    clean_text,
    extract_json_assignment,
    extract_json_script_by_id,
    make_soup,
    walk_dicts,
)
from app.services.extract_service.platforms.douyin import DOUYIN_DESKTOP_HEADERS

from .base import (
    BaseProfileExtractor,
    ExtractError,
    ExtractedProfile,
    ExtractedProfileWork,
    count_value,
    display_count,
)


class DouyinProfileExtractor(BaseProfileExtractor):
    platform = "douyin"

    def fetch(self):
        response = self.session.get(
            self.url,
            allow_redirects=True,
            timeout=self.timeout,
            headers=DOUYIN_DESKTOP_HEADERS,
        )
        response.raise_for_status()
        return response

    def extract(self) -> ExtractedProfile:
        response = self.fetch()
        try:
            return self.parse(response.text, response.url)
        except ExtractError:
            renderer = self.browser_renderer
            if renderer is None:
                from app.services.extract_service.public_browser import (
                    PublicBrowserRenderer,
                )

                renderer = PublicBrowserRenderer()
            rendered = renderer.render(self.url, timeout=self.timeout)
            profile = self.parse(rendered.html, rendered.url)
            return _enrich_from_browser_payloads(
                profile,
                rendered.payloads,
                limit=self.limit,
            )

    def parse(self, html: str, resolved_url: str) -> ExtractedProfile:
        soup = make_soup(html)
        state = (
            extract_json_script_by_id(soup, "RENDER_DATA")
            or extract_json_assignment(html, "window._ROUTER_DATA")
            or extract_json_assignment(html, "window.__INITIAL_STATE__")
        )
        profile = _profile_card(state)
        if profile is None:
            return _profile_from_dom(
                soup,
                url=self.url,
                resolved_url=resolved_url,
                limit=self.limit,
            )

        labels = {
            "following": display_count(
                _first(profile, "following_count", "followingCount")
            ),
            "followers": display_count(
                _first(profile, "follower_count", "followerCount", "fans_count")
            ),
            "liked": display_count(
                _first(profile, "total_favorited", "totalFavorited", "liked_count")
            ),
            "worksCount": display_count(
                _first(profile, "aweme_count", "awemeCount", "works_count")
            ),
        }
        return ExtractedProfile(
            platform=self.platform,
            url=self.url,
            resolved_url=resolved_url,
            name=clean_text(_first(profile, "nickname", "name")) or "",
            account_id=str(
                _first(profile, "unique_id", "short_id", "sec_uid", "uid") or ""
            ),
            avatar=_avatar_url(profile),
            description=clean_text(_first(profile, "signature", "desc", "description")) or "",
            following=count_value(labels["following"]),
            followers=count_value(labels["followers"]),
            liked=count_value(labels["liked"]),
            works_count=count_value(labels["worksCount"]),
            metric_labels={key: value for key, value in labels.items() if value},
            works=_works(state, self.limit),
            raw={"source": _source_name(html, soup)},
        )


def _profile_card(state: dict[str, Any]) -> dict[str, Any] | None:
    metric_keys = {
        "following_count",
        "followingCount",
        "follower_count",
        "followerCount",
        "fans_count",
        "total_favorited",
        "totalFavorited",
        "aweme_count",
        "awemeCount",
    }
    for item in walk_dicts(state):
        has_identity = any(
            key in item for key in ("nickname", "unique_id", "sec_uid", "uid")
        )
        if metric_keys.intersection(item) and has_identity:
            return item
    return None


def _works(state: dict[str, Any], limit: int) -> list[ExtractedProfileWork]:
    works: list[ExtractedProfileWork] = []
    seen: set[str] = set()
    for item in walk_dicts(state):
        work_id = str(item.get("aweme_id") or item.get("awemeId") or "").strip()
        if not work_id or work_id in seen:
            continue
        if not any(key in item for key in ("desc", "video", "images", "statistics")):
            continue
        seen.add(work_id)
        works.append(
            ExtractedProfileWork(
                id=work_id,
                url=str(
                    item.get("share_url")
                    or f"https://www.douyin.com/video/{work_id}"
                ),
                title=clean_text(item.get("desc") or item.get("title")) or "",
                cover=_work_cover(item),
                published_at=str(item.get("create_time") or item.get("createTime") or ""),
            )
        )
        if len(works) >= limit:
            break
    return works


def _first(item: dict[str, Any], *keys: str) -> Any:
    return next((item.get(key) for key in keys if item.get(key) is not None), None)


def _url_list(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    urls = value.get("url_list") or value.get("urlList")
    return str(urls[0]) if isinstance(urls, list) and urls else ""


def _avatar_url(profile: dict[str, Any]) -> str:
    for key in ("avatar_larger", "avatar_medium", "avatar_thumb", "avatar_url"):
        if url := _url_list(profile.get(key)):
            return url
    return ""


def _work_cover(item: dict[str, Any]) -> str:
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    for value in (video.get("cover"), video.get("origin_cover"), item.get("cover")):
        if url := _url_list(value):
            return url
    images = item.get("images")
    if isinstance(images, list) and images:
        return _url_list(images[0])
    return ""


def _source_name(html: str, soup) -> str:
    if extract_json_script_by_id(soup, "RENDER_DATA"):
        return "RENDER_DATA"
    if "window._ROUTER_DATA" in html:
        return "_ROUTER_DATA"
    return "INITIAL_STATE"


def _profile_from_dom(
    soup,
    *,
    url: str,
    resolved_url: str,
    limit: int,
) -> ExtractedProfile:
    user_info = soup.find(attrs={"data-e2e": "user-info"})
    if user_info is None:
        raise ExtractError("抖音公开主页未返回可解析的博主信息")

    name_node = user_info.find("h1")
    name = clean_text(name_node.get_text(" ", strip=True) if name_node else "") or ""
    labels = {
        "following": _dom_metric(user_info, "user-info-follow"),
        "followers": _dom_metric(user_info, "user-info-fans"),
        "liked": _dom_metric(user_info, "user-info-like"),
    }
    works_count_node = soup.find(attrs={"data-e2e": "user-tab-count"})
    works_count_label = clean_text(
        works_count_node.get_text(" ", strip=True) if works_count_node else ""
    ) or ""
    if works_count_label:
        labels["worksCount"] = works_count_label

    user_text = user_info.get_text("\n", strip=True)
    account_match = re.search(r"抖音号[：:]\s*([^\s]+)", user_text)
    return ExtractedProfile(
        platform="douyin",
        url=url,
        resolved_url=resolved_url,
        name=name,
        account_id=account_match.group(1) if account_match else "",
        avatar=_dom_avatar(soup),
        description=_dom_description(user_info),
        following=count_value(labels["following"]),
        followers=count_value(labels["followers"]),
        liked=count_value(labels["liked"]),
        works_count=count_value(works_count_label),
        metric_labels={key: value for key, value in labels.items() if value},
        works=_dom_works(soup, limit),
        raw={"source": "rendered_dom"},
    )


def _dom_metric(user_info, data_e2e: str) -> str:
    node = user_info.find(attrs={"data-e2e": data_e2e})
    if node is None:
        return ""
    candidates = [
        *node.stripped_strings,
        node.get("title") or "",
        node.get("aria-label") or "",
    ]
    for candidate in candidates:
        match = re.search(
            r"(?<!\d)(\d[\d,]*(?:\.\d+)?\s*(?:亿|万|[wWkK])?\+?)(?!\d)",
            str(candidate),
        )
        if match and count_value(match.group(1)) is not None:
            return match.group(1).replace(" ", "")
    return ""


def _dom_avatar(soup) -> str:
    detail = soup.find(attrs={"data-e2e": "user-detail"})
    root = detail or soup
    for image in root.find_all("img"):
        src = str(
            image.get("src")
            or image.get("data-src")
            or image.get("data-lazy-src")
            or ""
        ).strip()
        alt = str(image.get("alt") or "")
        if src and (
            "头像" in alt
            or "avatar" in alt.lower()
            or "aweme-avatar" in src
            or "/avatar/" in src
        ):
            return src if src.startswith("http") else f"https:{src}"
    avatar = root.find(attrs={"data-e2e": "user-avatar"})
    if avatar is not None:
        style = str(avatar.get("style") or "")
        match = re.search(r"url\([\"']?([^\"')]+)", style)
        if match:
            return match.group(1)
    return ""


def _dom_description(user_info) -> str:
    identity = user_info.find("p")
    description = identity.find_next_sibling("div") if identity else None
    if description is None:
        return ""
    text = clean_text(description.get_text(" ", strip=True)) or ""
    return re.sub(r"\s*更多\s*$", "", text).strip()


def _dom_works(soup, limit: int) -> list[ExtractedProfileWork]:
    container = soup.find(attrs={"data-e2e": "user-post-list"})
    if container is None:
        return []
    result: list[ExtractedProfileWork] = []
    seen: set[str] = set()
    for anchor in container.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        parsed = urlparse(href)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[0] not in {"video", "note"}:
            continue
        work_id = parts[1]
        if work_id in seen:
            continue
        seen.add(work_id)
        image = anchor.find("img")
        result.append(
            ExtractedProfileWork(
                id=work_id,
                url=f"https://www.douyin.com/{parts[0]}/{work_id}",
                title=clean_text(anchor.get_text(" ", strip=True)) or "",
                cover=str(image.get("src") or "") if image else "",
            )
        )
        if len(result) >= limit:
            break
    return result


def _enrich_from_browser_payloads(
    profile: ExtractedProfile,
    payloads: tuple[dict[str, Any], ...],
    *,
    limit: int,
) -> ExtractedProfile:
    if not payloads:
        return profile
    state = {"responses": list(payloads)}
    api_profile = _profile_card(state)
    works = _works(state, limit)
    if api_profile is None:
        return replace(profile, works=works or profile.works)

    labels = {
        "following": display_count(
            _first(api_profile, "following_count", "followingCount")
        ),
        "followers": display_count(
            _first(
                api_profile,
                "follower_count",
                "followerCount",
                "fans_count",
            )
        ),
        "liked": display_count(
            _first(
                api_profile,
                "total_favorited",
                "totalFavorited",
                "liked_count",
            )
        ),
        "worksCount": display_count(
            _first(api_profile, "aweme_count", "awemeCount", "works_count")
        ),
    }
    following = count_value(labels["following"])
    followers = count_value(labels["followers"])
    liked = count_value(labels["liked"])
    works_count = count_value(labels["worksCount"])
    merged_labels = dict(profile.metric_labels)
    merged_labels.update({key: value for key, value in labels.items() if value})
    return replace(
        profile,
        name=clean_text(_first(api_profile, "nickname", "name")) or profile.name,
        account_id=str(
            _first(api_profile, "unique_id", "short_id", "sec_uid", "uid")
            or profile.account_id
        ),
        avatar=_avatar_url(api_profile) or profile.avatar,
        description=clean_text(
            _first(api_profile, "signature", "desc", "description")
        )
        or profile.description,
        following=following if following is not None else profile.following,
        followers=followers if followers is not None else profile.followers,
        liked=liked if liked is not None else profile.liked,
        works_count=works_count if works_count is not None else profile.works_count,
        metric_labels=merged_labels,
        works=works or profile.works,
        raw={"source": "browser_public_api"},
    )
