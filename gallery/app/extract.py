"""No-login Douyin / Xiaohongshu share-link extraction.

Both platforms are HTTP-only:

* Douyin resolves the short link, then reads the public share page
  (second response carries the work JSON). Image posts use url_list
  without the watermark template. Videos use watermark=0.
* Xiaohongshu reads window.__INITIAL_STATE__ and downloads each image
  by fileId, without the !h5_1080jpg / !style_ rendition.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

URL_RE = re.compile(r"https?://[^\s<>\"'`，。！？；、）)\]]+", re.I)
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")
_BARE_HOST = re.compile(
    r"(?<![\w.])((?:v\.douyin\.com|www\.iesdouyin\.com|www\.douyin\.com|xhslink\.com|www\.xiaohongshu\.com)/[^\s<>\"'`，。！？；、）)\]]+)",
    re.I,
)
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)
# Share HTML only embeds the work JSON for a mobile browser profile, and
# only on the request after the cookie is set.
SHARE_UA = (
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
XHS_IMG_HOST = "https://sns-img-qc.xhscdn.com"
_VIDEO_URI = re.compile(r"v[0-9a-zA-Z]{8,}")


class ExtractError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Media:
    type: str
    url: str
    quality: str = ""
    ext: str = ""
    no_watermark: bool | None = None
    cover: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Comment:
    author: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Extracted:
    platform: str
    content_id: str
    source_url: str
    canonical_url: str
    title: str = ""
    content: str = ""
    author: str = ""
    cover: str | None = None
    tags: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    comment_count: int | None = None
    kind: str = "unknown"
    medias: list[Media] = field(default_factory=list)
    via: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["medias"] = [media.to_dict() for media in self.medias]
        data["comments"] = [comment.to_dict() for comment in self.comments]
        return data


def extract_urls(text: str) -> list[str]:
    found = []
    cleaned = _INVISIBLE.sub("", text or "")
    for pattern in (URL_RE, _BARE_HOST):
        for match in pattern.finditer(cleaned):
            url = match.group(0).rstrip(".,;:!?）)》»\"'")
            if "，" in url:
                url = url.split("，", 1)[0]
            if not url.startswith("http"):
                url = "https://" + url
            if url not in found:
                found.append(url)
    return found


def detect(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if "douyin" in host or "iesdouyin" in host:
        return "douyin"
    if "xiaohongshu" in host or "xhslink" in host or host.endswith("xhscdn.com"):
        return "xhs"
    return None


def pick(text: str) -> tuple[str, str]:
    urls = extract_urls(text)
    for url in urls:
        platform = detect(url)
        if platform:
            return url, platform
    if urls:
        raise ExtractError("unsupported_link", "只支持抖音和小红书分享链接")
    body = text or ""
    if re.search(r"[A-Za-z]{2,12}:/", body) and ("抖音" in body or "Dou音" in body):
        raise ExtractError(
            "unsupported_link",
            "这段是抖音搜索口令，里面没有 v.douyin.com 短链。请再复制一次，带上 https://v.douyin.com/ 开头的那一段。",
        )
    raise ExtractError("unsupported_link", "没有找到链接")


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        timeout=20,
        follow_redirects=True,
        trust_env=False,
    )


def _douyin_id(url: str) -> tuple[str | None, str]:
    path = urlparse(url).path or ""
    m = re.search(r"/(video|note|slides)/(\d{6,})", path)
    if m:
        return m.group(2), m.group(1)
    q = urlparse(url).query
    m = re.search(r"(?:modal_id|aweme_id)=(\d{6,})", q)
    if m:
        return m.group(1), "video"
    return None, "video"


def _xhs_id(url: str) -> str | None:
    raw = unquote(unquote(url or ""))
    m = re.search(r"/(?:explore|discovery/item|item)/([0-9a-fA-F]{16,})", raw)
    return m.group(1).lower() if m else None


def _uniq(items: list[Media]) -> list[Media]:
    seen: set[str] = set()
    out: list[Media] = []
    for m in items:
        if not m.url or m.url in seen:
            continue
        seen.add(m.url)
        out.append(m)
    return out


def _kind(medias: list[Media]) -> str:
    types = {m.type for m in medias}
    if "video" in types and "image" in types:
        return "mixed"
    if "video" in types:
        return "video"
    if "image" in types:
        return "image"
    return "unknown"


def _tags(text: str) -> list[str]:
    found = []
    for raw in re.findall(r"#([^\s#]{1,40})", text or ""):
        tag = raw.rstrip(".,;:!?，。！？；、》」』）)]}")
        tag = re.sub(r"\[话题\]?$", "", tag)
        if tag and tag not in found:
            found.append(tag)
    return found


def _caption_and_tags(text: str, extra_tags: list[str] | None = None) -> tuple[str, list[str]]:
    """文案去掉 #标签，标签单独返回。"""
    tags = _tags(text)
    for tag in extra_tags or []:
        clean = re.sub(r"\[话题\]?$", "", (tag or "").strip())
        if clean and clean not in tags:
            tags.append(clean)
    caption = re.sub(r"#[^\s#]+", " ", text or "")
    caption = re.sub(r"\s*-\s*\S+于\d{8}发布在抖音.*$", "", caption)
    caption = re.sub(r"\s+", " ", caption).strip(" \n-")
    return caption, tags


def _nwm_url(video_uri: str) -> str:
    return (
        "https://api.amemv.com/aweme/v1/play/"
        f"?video_id={video_uri}&line=0&watermark=0&ratio=1080p"
    )


def _addr_urls(addr: Any) -> list[str]:
    if not isinstance(addr, dict):
        return []
    urls = []
    for u in addr.get("url_list") or []:
        if isinstance(u, str) and u.startswith("http"):
            urls.append(u.replace("\\u0026", "&"))
    return urls


def _best_image(urls: list[Any]) -> str | None:
    """Prefer a jpeg that is not the Douyin watermark template."""
    clean: list[str] = []
    for u in urls:
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        if "tplv-dy-water" in u or "playwm" in u:
            continue
        clean.append(u.replace("\\u0026", "&"))
    for u in clean:
        path = u.split("?", 1)[0].lower()
        if path.endswith(".jpeg") or path.endswith(".jpg"):
            return u
    return clean[-1] if clean else None


def _image_ext(url: str) -> str:
    path = url.split("?", 1)[0].lower()
    if path.endswith(".webp"):
        return "webp"
    if path.endswith(".png"):
        return "png"
    return "jpg"


def _video_uri(video: dict[str, Any]) -> str | None:
    for key in ("play_addr", "play_addr_h264", "play_addr_bytevc1"):
        uri = (video.get(key) or {}).get("uri") if isinstance(video.get(key), dict) else None
        if isinstance(uri, str) and _VIDEO_URI.fullmatch(uri):
            return uri
    return None


def _image_urls(img: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for u in img.get("url_list") or []:
        if isinstance(u, str):
            urls.append(u)
    for val in img.values():
        if isinstance(val, dict):
            for u in val.get("url_list") or []:
                if isinstance(u, str):
                    urls.append(u)
    return urls


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _comment_rows(raw: Any, limit: int = 30) -> list[Comment]:
    rows: Any = raw
    if isinstance(raw, dict):
        rows = raw.get("list") or raw.get("comments") or raw.get("commentList") or raw.get("comment_list") or []
    if not isinstance(rows, list):
        return []
    found: list[Comment] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = row.get("text") or row.get("content") or row.get("comment") or ""
        if not isinstance(text, str) or not text.strip():
            continue
        user = row.get("user") or row.get("userInfo") or row.get("user_info") or {}
        author = ""
        if isinstance(user, dict):
            nick = user.get("nickname") or user.get("nickName") or user.get("name") or ""
            author = nick.strip() if isinstance(nick, str) else ""
        found.append(Comment(author, text.strip()[:500]))
        if len(found) >= limit:
            break
    return found


def _hashtag_names(detail: dict[str, Any]) -> list[str]:
    names = []
    for extra in detail.get("text_extra") or []:
        if isinstance(extra, dict) and isinstance(extra.get("hashtag_name"), str):
            names.append(extra["hashtag_name"])
    return names


def _from_aweme(detail: dict[str, Any], aweme_id: str, source: str, canonical: str, via: str) -> Extracted:
    video = detail.get("video") or {}
    desc = (detail.get("desc") or "").strip()
    author = ((detail.get("author") or {}).get("nickname") or "").strip()
    images = [img for img in (detail.get("images") or detail.get("image_infos") or []) if isinstance(img, dict)]
    medias: list[Media] = []
    cover = None
    # 图文：有图片列表就只出图，不把配乐/幻灯片地址当成视频。
    if images:
        for img in images:
            u = _best_image(_image_urls(img))
            if not u:
                continue
            medias.append(Media("image", u, quality="原图", ext=_image_ext(u), no_watermark=True, cover=u))
        if medias:
            cover = medias[0].cover
    else:
        uri = _video_uri(video)
        if uri:
            medias.append(Media("video", _nwm_url(uri), quality="1080p", ext="mp4", no_watermark=True))
        for key in ("origin_cover", "cover"):
            picked = _best_image(_addr_urls(video.get(key)))
            if picked:
                cover = picked
                break
    caption, tags = _caption_and_tags(desc, _hashtag_names(detail))
    stats = detail.get("statistics") if isinstance(detail.get("statistics"), dict) else {}
    return Extracted(
        platform="douyin",
        content_id=str(detail.get("aweme_id") or aweme_id),
        source_url=source,
        canonical_url=canonical,
        title=caption[:80] or desc[:80],
        content=caption,
        author=author,
        cover=cover,
        tags=tags,
        kind=_kind(medias),
        comments=_comment_rows(detail.get("comment_list") or detail.get("comments")),
        comment_count=_count(stats.get("comment_count")),
        medias=_uniq(medias),
        via=via,
    )


def _aweme_usable(item: dict[str, Any]) -> bool:
    images = item.get("images") or item.get("image_infos") or []
    if isinstance(images, list) and any(isinstance(img, dict) and _best_image(_image_urls(img)) for img in images):
        return True
    return _video_uri(item.get("video") or {}) is not None


def _item_from_html(html: str) -> dict[str, Any] | None:
    data = _balanced_json_after(html, "window._ROUTER_DATA")
    if not isinstance(data, dict):
        return None
    for node in (data.get("loaderData") or {}).values():
        if not isinstance(node, dict):
            continue
        info = node.get("videoInfoRes")
        if not isinstance(info, dict):
            continue
        items = info.get("item_list") or []
        if items and isinstance(items[0], dict):
            return items[0]
    return None


def _kind_order(kind: str) -> list[str]:
    first = kind if kind in ("video", "note", "slides") else "video"
    return [first, *[k for k in ("note", "slides", "video") if k != first]]


def _load_share_item(client: httpx.Client, aweme_id: str, kind: str) -> dict[str, Any] | None:
    """图文只在 /share/note 或 /share/slides 里，视频页经常是空的，所以按类型依次试。"""
    for page_kind in _kind_order(kind):
        url = f"https://www.iesdouyin.com/share/{page_kind}/{aweme_id}"
        for _ in range(3):
            html = client.get(url, headers={"User-Agent": SHARE_UA}).text
            item = _item_from_html(html)
            if item and _aweme_usable(item):
                return item
    return None


def extract_douyin(client: httpx.Client, source_url: str) -> Extracted:
    resolved = client.get(source_url, headers={"User-Agent": MOBILE_UA})
    canonical = str(resolved.url)
    aweme_id, kind = _douyin_id(canonical)
    if not aweme_id:
        aweme_id, kind = _douyin_id(source_url)
    if not aweme_id:
        raise ExtractError("resolve_failed", "无法从抖音链接解析出作品 ID")
    item = _load_share_item(client, aweme_id, kind)
    if not item:
        raise ExtractError(
            "detail_failed",
            "抖音公开分享页没有返回作品。公开作品不需要登录；已删除或仅 App 可见时会失败。",
        )
    images = item.get("images") or item.get("image_infos") or []
    page_kind = "note" if isinstance(images, list) and images else "video"
    page = f"https://www.douyin.com/{page_kind}/{aweme_id}"
    got = _from_aweme(item, aweme_id, source_url, page, via="share.page")
    if not got.medias:
        raise ExtractError("detail_failed", "作品里没有可提取的图片或视频")
    return got


def _balanced_json_after(html: str, marker: str) -> dict[str, Any] | None:
    i = html.find(marker)
    if i < 0:
        return None
    start = html.find("{", i)
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    quote = ""
    for j in range(start, min(len(html), start + 4_000_000)):
        ch = html[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html[start : j + 1].replace("undefined", "null")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None
    return None


def _https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _classify_video_bytes(data: bytes, content_type: str = "", url: str = "") -> str | None:
    """mp4 container, QuickTime mov, or HLS playlist."""
    path = (url or "").split("?", 1)[0].lower()
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if path.endswith(".m3u8") or "mpegurl" in ctype or data.startswith(b"#EXTM3U"):
        return "hls"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        if data[8:12] == b"qt  ":
            return "mov"
        return "mp4"
    if "quicktime" in ctype:
        return "mov"
    if ctype == "video/mp4":
        return "mp4"
    return None


def _sniff_video(client: httpx.Client, url: str) -> str | None:
    headers = {
        "Referer": "https://www.xiaohongshu.com/",
        "User-Agent": MOBILE_UA,
        "Range": "bytes=0-31",
    }
    try:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code >= 400:
                return None
            data = b""
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) >= 32:
                    break
            return _classify_video_bytes(data, resp.headers.get("content-type") or "", str(resp.url))
    except httpx.HTTPError:
        return None


def _xhs_video_candidates(note: dict[str, Any]) -> list[tuple[str, str]]:
    """Origin first, then direct (non-HLS) play URLs, h264 before other codecs."""
    out: list[tuple[str, str]] = []
    origin = (((note.get("video") or {}).get("consumer") or {}).get("originVideoKey"))
    if isinstance(origin, str) and origin.strip() and "m3u8" not in origin.lower():
        out.append(("origin", f"https://sns-video-bd.xhscdn.com/{origin.strip().lstrip('/')}"))
    streams = (((note.get("video") or {}).get("media") or {}).get("stream") or {})
    if not isinstance(streams, dict):
        return out
    keys = [k for k in ("h264", "h265", "av1") if k in streams]
    keys += [k for k in streams if k not in keys]
    for key in keys:
        group = streams.get(key)
        if not isinstance(group, list):
            continue
        infos = [i for i in group if isinstance(i, dict)]
        infos.sort(key=lambda i: int(i.get("size") or i.get("videoBitrate") or 0), reverse=True)
        for info in infos[:1]:
            raw = info.get("masterUrl")
            if not isinstance(raw, str) or not raw.startswith("http"):
                continue
            if ".m3u8" in raw.split("?", 1)[0].lower():
                continue
            out.append((str(key), _https(raw)))
    return out


def as_mp4_start(data: bytes) -> bytes:
    """Keep the original picture. A QuickTime ftyp brand is rewritten so the file is an MP4."""
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] == b"qt  ":
        return data[:8] + b"mp42" + data[12:]
    return data


def _select_xhs_video(candidates: list[tuple[str, str]], kinds: list[str | None]) -> str | None:
    """Origin has no watermark, including when its container is QuickTime. Play URLs are the watermarked fallback."""
    for (label, url), kind in zip(candidates, kinds):
        if label == "origin" and kind != "hls":
            return url
    for (_, url), kind in zip(candidates, kinds):
        if kind == "mp4":
            return url
    for _, url in candidates:
        if url.split("?", 1)[0].lower().endswith(".mp4"):
            return url
    return None


def _xhs_video_url(client: httpx.Client, note: dict[str, Any]) -> str | None:
    candidates = _xhs_video_candidates(note)
    origin = next((url for label, url in candidates if label == "origin"), None)
    if origin:
        if _sniff_video(client, origin) != "hls":
            return origin
        candidates = [(label, url) for label, url in candidates if label != "origin"]
    kinds: list[str | None] = []
    for _, url in candidates:
        kind = _sniff_video(client, url)
        kinds.append(kind)
        if kind == "mp4":
            return url
    return _select_xhs_video(candidates, kinds)


def _xhs_file_url(image: dict[str, Any]) -> str | None:
    """Original file, no !h5_1080jpg / !style_ watermark rendition."""
    file_id = image.get("fileId") or image.get("file_id")
    if isinstance(file_id, str):
        file_id = file_id.strip().lstrip("/")
        if file_id and "!" not in file_id and not file_id.startswith("http"):
            return f"{XHS_IMG_HOST}/{file_id}"
    for key in ("urlDefault", "url", "urlPre"):
        raw = image.get(key)
        if not isinstance(raw, str) or "xhscdn.com/" not in raw:
            continue
        path = urlparse(raw).path.lstrip("/").split("!", 1)[0]
        if path:
            return f"{XHS_IMG_HOST}/{path}"
    for info in image.get("infoList") or []:
        if not isinstance(info, dict):
            continue
        raw = info.get("url")
        if isinstance(raw, str) and "xhscdn.com/" in raw:
            path = urlparse(raw).path.lstrip("/").split("!", 1)[0]
            if path:
                return f"{XHS_IMG_HOST}/{path}"
    return None


def extract_xhs(client: httpx.Client, source_url: str) -> Extracted:
    # Desktop UA is sent to the login wall. The in-app share link opens on mobile.
    r = client.get(
        source_url,
        headers={"Referer": "https://www.xiaohongshu.com/", "User-Agent": MOBILE_UA},
    )
    canonical = str(r.url)
    note_id = _xhs_id(canonical) or _xhs_id(source_url)
    html = r.text or ""
    if note_id and ("/login" in canonical or "noteDetailMap" not in html and "noteData" not in html):
        page = f"https://www.xiaohongshu.com/discovery/item/{note_id}"
        r = client.get(page, headers={"Referer": "https://www.xiaohongshu.com/", "User-Agent": MOBILE_UA})
        canonical = str(r.url)
        html = r.text or ""
    if not note_id:
        raise ExtractError("resolve_failed", "无法从小红书链接解析出笔记 ID")
    if "window.__INITIAL_STATE__" not in html:
        raise ExtractError(
            "detail_failed",
            "小红书公开页没有笔记数据。公开笔记不需要登录；若被验证码拦住，请稍后重试。",
        )

    state = _balanced_json_after(html, "window.__INITIAL_STATE__")
    note = None
    entry: dict[str, Any] = {}
    if isinstance(state, dict):
        mapped = ((state.get("note") or {}).get("noteDetailMap") or {}).get(note_id) or {}
        if isinstance(mapped, dict):
            entry = mapped
            note = mapped.get("note")
        if not isinstance(note, dict):
            note = ((state.get("noteData") or {}).get("data") or {}).get("noteData")
            entry = {}
    if not isinstance(note, dict):
        raise ExtractError(
            "detail_failed",
            "小红书公开页没有笔记数据。公开笔记不需要登录；若被验证码拦住，请稍后重试。",
        )

    title = (note.get("title") or "").strip()
    desc = (note.get("desc") or "").strip()
    author = ((note.get("user") or {}).get("nickName") or "").strip()
    named = [t.get("name") for t in (note.get("tagList") or []) if isinstance(t, dict) and t.get("name")]
    caption, tags = _caption_and_tags(f"{title}\n{desc}".strip(), named)
    interact = note.get("interactInfo") if isinstance(note.get("interactInfo"), dict) else {}
    comments = _comment_rows(entry.get("comments") or note.get("comments") or note.get("commentList"))
    comment_count = _count(interact.get("commentCount") or interact.get("comment_count"))
    images: list[Media] = []
    cover = None
    for image in note.get("imageList") or []:
        if not isinstance(image, dict):
            continue
        u = _xhs_file_url(image)
        if u:
            if not cover:
                cover = u
            images.append(Media("image", u, quality="原图", ext="jpg", no_watermark=True, cover=u))
    video_url = _xhs_video_url(client, note)
    if video_url:
        medias = [Media("video", video_url, quality="原片", ext="mp4", no_watermark=True)]
    else:
        medias = _uniq(images)
    if not medias:
        raise ExtractError("detail_failed", "笔记里没有可提取的图片或视频")
    return Extracted(
        platform="xhs",
        content_id=note_id,
        source_url=source_url,
        canonical_url=canonical if _xhs_id(canonical) else f"https://www.xiaohongshu.com/explore/{note_id}",
        title=caption[:80] or title,
        content=caption,
        author=author,
        cover=cover,
        tags=tags,
        comments=comments,
        comment_count=comment_count,
        kind=_kind(medias),
        medias=medias,
        via="initial_state",
    )


def extract(text: str) -> Extracted:
    source, platform = pick(text)
    with _client() as client:
        if platform == "douyin":
            return extract_douyin(client, source)
        return extract_xhs(client, source)


def decode_proxy_target(url: str) -> str:
    return unquote(url)
