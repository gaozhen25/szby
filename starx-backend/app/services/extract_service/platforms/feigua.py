import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from app.services.extract_service.douyin_profile_resolver import resolve_douyin_profile_url
from app.services.extract_service.platforms.base import BaseExtractor, clean_text


class Feigua(BaseExtractor):
    """解析飞瓜公开播主页。

    页面中的抖音主页二维码由前端根据 ``data-qrcodesrc`` 动态生成。直接读取
    这个二维码原始载荷比渲染页面后再识别位图更准确，也不需要额外图像依赖。
    """

    platform = "feigua"

    def __init__(self, *args, profile_resolver=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile_resolver = profile_resolver or resolve_douyin_profile_url

    def extract(self):
        result = super().extract()
        profile = result.raw["profile"]
        resolution = self.profile_resolver(
            profile.get("douyin_id") or "",
            profile.get("nickname") or "",
        )
        result.raw["douyin_profile_resolution"] = resolution
        if resolution.get("status") == "resolved":
            profile["douyin_profile_url"] = resolution.get("profile_url")
        return result

    def parse(self, html: str, soup: BeautifulSoup, resolved_url: str):
        nickname = _nickname(soup)
        biography = _text_of(soup.select_one(".owner-info .intro span"))
        avatar_url = _attribute(soup.select_one(".owner-info .avatar img"), "src")
        douyin_share_url = douyin_profile_url_from_qr(html, soup)
        metric_displays = _profile_metric_displays(soup)
        overview_displays = _overview_displays(soup)

        raw = {
            "profile": {
                "nickname": nickname,
                "douyin_id": _douyin_id(soup),
                "biography": biography,
                "avatar_url": avatar_url,
                "douyin_share_url": douyin_share_url,
                "douyin_profile_url": None,
            },
            "metrics": {
                key: _metric_value(value, percentage=key.endswith("_percent"))
                for key, value in metric_displays.items()
            },
            "metric_displays": metric_displays,
            "overview": {
                period: {key: _metric_value(value) for key, value in values.items()}
                for period, values in overview_displays.items()
            },
            "overview_displays": overview_displays,
            "qr": {
                "payload": douyin_share_url,
                "source": "data-qrcodesrc" if douyin_share_url else None,
            },
        }

        return self.from_page(
            soup,
            resolved_url,
            title=nickname,
            description=biography,
            images=[avatar_url] if avatar_url else [],
            videos=[],
            content_type="profile",
            include_meta_media=False,
            raw=raw,
        )


def douyin_profile_url_from_qr(html: str, soup: BeautifulSoup) -> str | None:
    """取得“查看抖音主页”二维码中编码的 URL。"""

    for element in soup.select("[data-qrcodesrc]"):
        candidate = _attribute(element, "data-qrcodesrc")
        if _is_douyin_profile_url(candidate):
            return candidate

    # 兼容精简 DOM 解析器或属性被周边脚本序列化的页面。
    for match in re.finditer(
        r"data-qrcodesrc\s*=\s*(['\"])(?P<url>https?://.+?)\1",
        html,
        flags=re.I,
    ):
        candidate = match.group("url").replace("&amp;", "&")
        if _is_douyin_profile_url(candidate):
            return candidate
    return None


def _is_douyin_profile_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    trusted_host = any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ("douyin.com", "iesdouyin.com")
    )
    return trusted_host and "/user/" in parsed.path


def _nickname(soup: BeautifulSoup) -> str | None:
    element = soup.select_one(".owner-info .nickname")
    if not element:
        return None
    direct_text = " ".join(
        str(child).strip()
        for child in element.children
        if isinstance(child, NavigableString) and str(child).strip()
    )
    return clean_text(direct_text)


def _douyin_id(soup: BeautifulSoup) -> str | None:
    for item in soup.select(".owner-info .info li"):
        text = _text_of(item) or ""
        match = re.search(r"抖音号[：:]\s*(\S+)", text)
        if match:
            return match.group(1)
    return None


def _profile_metric_displays(soup: BeautifulSoup) -> dict[str, str]:
    container = soup.select_one(".owner-data")
    if not container:
        return {}

    labels = {
        "粉丝数": "followers_count",
        "作品数": "works_count",
        "飞瓜指数": "feigua_index",
        "昨日排名打败": "yesterday_rank_beaten_percent",
        "近一周排名打败": "week_rank_beaten_percent",
        "总点赞": "total_likes",
        "平均点赞": "average_likes",
        "集均评论": "average_comments",
        "集均分享": "average_shares",
    }
    result: dict[str, str] = {}
    for block in container.select(".row > div"):
        block_text = _text_of(block) or ""
        key = next((field for label, field in labels.items() if label in block_text), None)
        value = _text_of(block.select_one("span"))
        if key and value:
            result[key] = value
    return result


def _overview_displays(soup: BeautifulSoup) -> dict[str, dict[str, str]]:
    periods = {
        "近7天": "7d",
        "7天": "7d",
        "30天": "30d",
        "90天": "90d",
    }
    labels = {
        "最新作品数": "latest_works",
        "粉丝增量": "followers_change",
        "新增点赞": "likes_change",
        "新增评论": "comments_change",
        "新增转发": "shares_change",
        "新增直播": "live_streams_change",
    }
    buttons = soup.select("#js-over-view-filter > button")
    sections = soup.select("#js-over-view-section > .js-blogger-overview")
    result: dict[str, dict[str, str]] = {}
    for button, section in zip(buttons, sections):
        period_label = _attribute(button, "data-value") or _text_of(button)
        period = periods.get(period_label or "")
        if not period:
            continue
        values: dict[str, str] = {}
        for heading in section.select("h5"):
            key = labels.get(_text_of(heading) or "")
            parent = heading.parent if isinstance(heading.parent, Tag) else None
            value = _text_of(parent.find(["p"]) if parent else None)
            if key and value:
                values[key] = value
        result[period] = values
    return result


def _metric_value(display: str, *, percentage: bool = False) -> int | float | None:
    text = (clean_text(display) or "").lower().replace(",", "")
    if not text or text in {"--", "-"}:
        return None
    if percentage:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None

    multiplier = 1
    if text.endswith("w") or text.endswith("万"):
        multiplier = 10_000
    elif text.endswith("k") or text.endswith("千"):
        multiplier = 1_000
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    value = float(match.group()) * multiplier
    return int(value) if value.is_integer() else value


def _attribute(element: Tag | None, name: str) -> str | None:
    if not element:
        return None
    value: Any = element.get(name)
    return clean_text(value)


def _text_of(element: Tag | None) -> str | None:
    return clean_text(element.get_text(" ", strip=True)) if element else None
