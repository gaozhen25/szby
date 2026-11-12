import re
from urllib.parse import urlparse

import requests

from app.services.extract_service.platforms.base import (
    BaseExtractor,
    collect_urls_from_text,
    extract_json_assignment,
    extract_json_script_by_id,
    first_quoted_value_from_text,
    first_string_from_keys,
    img_srcs_by_class,
    parse_json_like,
    unique_urls,
    walk_dicts,
)


# 抖音移动分享页需要手机 UA；PC UA 会落到空壳页，拿不到 RENDER_DATA/_ROUTER_DATA。
DOUYIN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

DOUYIN_DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.douyin.com/",
}


class Douyin(BaseExtractor):
    platform = "douyin"

    def fetch(self):
        mobile_url = douyin_mobile_share_url(self.url)
        try:
            response = self.session.get(
                mobile_url,
                allow_redirects=True,
                timeout=self.timeout,
                headers=DOUYIN_HEADERS,
            )
            response.raise_for_status()
            if douyin_response_has_payload(response.text):
                return response
        except requests.RequestException:
            pass

        # 移动分享域偶发 SSL/空壳页时，回退 PC 详情页。
        response = self.session.get(
            self.url,
            allow_redirects=True,
            timeout=self.timeout,
            headers=DOUYIN_DESKTOP_HEADERS,
        )
        response.raise_for_status()
        return response

    def parse(self, html, soup, resolved_url):
        render_data = douyin_page_data(html, soup)
        aweme = douyin_aweme_card(render_data)
        title = (
            (aweme.get("desc") if aweme else None)
            or first_string_from_keys(render_data, ("desc", "title"))
            or first_quoted_value_from_text(html, ("desc", "title"))
        )
        description = (
            (aweme.get("desc") if aweme else None)
            or first_string_from_keys(render_data, ("desc", "description"))
            or first_quoted_value_from_text(html, ("desc", "description"))
        )
        images = douyin_images(render_data, html)
        videos = douyin_videos(render_data, html)

        return self.from_page(
            soup,
            resolved_url,
            title=title,
            description=description,
            images=images,
            videos=videos[:1],
            content_type="video" if videos else ("image" if images else None),
            include_meta_media=False,
            raw={
                "render_data_found": bool(render_data),
                "source": (
                    "RENDER_DATA"
                    if extract_json_script_by_id(soup, "RENDER_DATA")
                    else ("_ROUTER_DATA" if render_data else None)
                ),
            },
        )


def douyin_response_has_payload(html: str) -> bool:
    return "RENDER_DATA" in html or "window._ROUTER_DATA" in html


def douyin_page_data(html, soup) -> dict:
    render_data = extract_json_script_by_id(soup, "RENDER_DATA")
    if render_data:
        return render_data
    return extract_json_assignment(html, "window._ROUTER_DATA")


def douyin_aweme_card(render_data: dict) -> dict | None:
    for item in walk_dicts(render_data):
        aweme_id = item.get("aweme_id") or item.get("awemeId")
        if not aweme_id:
            continue
        if any(key in item for key in ("desc", "video", "images", "statistics")):
            return item
    return None


def douyin_mobile_share_url(url):
    parsed = urlparse(url)
    if parsed.netloc.lower() != "www.douyin.com":
        return url
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) != 2 or path_parts[0] not in {"note", "video"}:
        return url
    return f"https://m.douyin.com/share/{path_parts[0]}/{path_parts[1]}"


def douyin_images(render_data, html):
    # 主作品的 images 之外，图文页还会在 image_infos 中放入多组清晰度档位，
    # 每个档位也使用 images 作为字段名。遍历整棵 JSON 会把同一组图片的
    # 原图、480p、960p 等不同 URL 都当成独立图片，因此先限定到作品卡片。
    aweme = douyin_aweme_card(render_data)
    if aweme:
        images = image_urls(aweme.get("images"))
        if images:
            return unique_urls(images)

    images = []
    for item in walk_dicts(render_data):
        images.extend(image_urls(item.get("images")))
    if images:
        return unique_urls(images)

    for image_list in json_values_for_key(html, "images"):
        images.extend(image_urls(image_list))
        if images:
            return unique_urls(images)

    dom_images = img_srcs_by_class(html, "gallery-container__carousel__image")
    if dom_images:
        return dom_images

    cover_images = []
    for item in walk_dicts(render_data):
        cover = item.get("cover")
        if not isinstance(cover, dict):
            continue
        url_list = cover.get("url_list")
        if isinstance(url_list, list) and url_list:
            cover_images.append(url_list[0])
    if cover_images:
        return unique_urls(cover_images)

    for video in json_values_for_key(html, "video"):
        if not isinstance(video, dict):
            continue
        cover = video.get("cover")
        if not isinstance(cover, dict):
            continue
        url_list = cover.get("url_list")
        if isinstance(url_list, list) and url_list:
            cover_images.append(url_list[0])
    if cover_images:
        return unique_urls(cover_images)

    return [
        url for url in collect_urls_from_text(html, r"biz_tag=aweme_images")
        if "aweme-avatar" not in url
    ]


def image_urls(image_list):
    if not isinstance(image_list, list):
        return []
    urls = []
    for image in image_list:
        if not isinstance(image, dict):
            continue
        url_list = image.get("url_list")
        if isinstance(url_list, list) and url_list:
            urls.append(url_list[0])
    return urls


def douyin_videos(render_data, html):
    videos = []
    for item in walk_dicts(render_data):
        videos.extend(play_addr_urls(item.get("video")))
        videos.extend(play_addr_urls(item))
    if videos:
        return unique_urls(videos)

    for video in json_values_for_key(html, "video"):
        videos.extend(play_addr_urls(video))
    if videos:
        return unique_urls(videos)

    return [
        normalize_douyin_video_url(url)
        for url in collect_urls_from_text(
            html, r"(?:aweme/v1/play|\.mp4(?:\?|$)|\.m3u8(?:\?|$))"
        )
        if is_video_url(url)
    ]


def play_addr_urls(video):
    if not isinstance(video, dict):
        return []
    # 与 MediaSpider 的抖音媒体提取顺序保持一致：优先 H.264，其次 256
    # 档位，最后才使用通用播放地址。同一档位里，抖音通常把带水印的
    # aweme/v1/play(wm) 地址放在前面，把无水印 CDN 地址放在末尾。
    # CDN 地址经常没有 .mp4 后缀，因此不能再用通用 URL 特征过滤掉它。
    for address_key in ("play_addr_h264", "play_addr_256", "play_addr"):
        play_addr = video.get(address_key)
        if not isinstance(play_addr, dict):
            continue
        url_list = play_addr.get("url_list")
        if not isinstance(url_list, list):
            continue
        valid_urls = [url for url in url_list if is_play_addr_url(url)]
        if valid_urls:
            return [normalize_douyin_video_url(valid_urls[-1])]
    return []


def normalize_douyin_video_url(url):
    """把分享页的带水印播放端点规范化为无水印播放端点。"""

    if not isinstance(url, str):
        return url
    return re.sub(
        r"(?i)(/aweme/v1/)playwm(?=/|$)",
        r"\1play",
        url,
        count=1,
    )


def is_play_addr_url(url):
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    lowered = url.lower()
    return not (
        ".mp3" in lowered
        or "images_no_sound" in lowered
        or "/ies-music/" in lowered
    )


def is_video_url(url):
    if not isinstance(url, str) or not url.startswith("http"):
        return False
    lowered = url.lower()
    if ".mp3" in lowered or "images_no_sound" in lowered or "/ies-music/" in lowered:
        return False
    return "aweme/v1/play" in lowered or ".mp4" in lowered or ".m3u8" in lowered


def json_values_for_key(text, key):
    values = []
    pattern = f'"{key}"'
    start = 0
    while True:
        key_index = text.find(pattern, start)
        if key_index < 0:
            break
        colon = text.find(":", key_index + len(pattern))
        if colon < 0:
            break
        value_start = next_non_space(text, colon + 1)
        if value_start is None or text[value_start] not in "[{":
            start = colon + 1
            continue
        value_end = matching_json_end(text, value_start)
        if value_end is None:
            start = value_start + 1
            continue
        fragment = text[value_start:value_end + 1]
        parsed = parse_json_like(fragment)
        if parsed:
            values.append(parsed)
        else:
            parsed_list = parse_json_list(fragment)
            if parsed_list is not None:
                values.append(parsed_list)
        start = value_end + 1
    return values


def parse_json_list(fragment):
    try:
        parsed = __import__("json").loads(fragment)
    except ValueError:
        return None
    return parsed if isinstance(parsed, list) else None


def next_non_space(text, index):
    while index < len(text):
        if not text[index].isspace():
            return index
        index += 1
    return None


def matching_json_end(text, start):
    opener = text[start]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        elif opener == "{" and char == "[":
            depth += 1
        elif opener == "{" and char == "]":
            depth -= 1
        elif opener == "[" and char == "{":
            depth += 1
        elif opener == "[" and char == "}":
            depth -= 1
    return None
