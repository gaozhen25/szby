import json
import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class ExtractError(RuntimeError):
    """Raised when a supported platform page cannot be parsed."""


@dataclass
class ExtractedContent:
    platform: str
    url: str
    resolved_url: str
    content_type: str = "unknown"
    title: str | None = None
    description: str | None = None
    images: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    cover: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "url": self.url,
            "resolved_url": self.resolved_url,
            "type": self.content_type,
            "title": self.title,
            "description": self.description,
            "images": self.images,
            "videos": self.videos,
            "cover": self.cover,
            "raw": self.raw,
        }


class BaseExtractor:
    platform = "unknown"

    def __init__(self, url: str, session: requests.Session | None = None, timeout: int = 10):
        self.url = url
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self):
        response = self.session.get(
            self.url,
            allow_redirects=True,
            timeout=self.timeout,
            headers=DEFAULT_HEADERS,
        )
        response.raise_for_status()
        return response

    def extract(self) -> ExtractedContent:
        response = self.fetch()
        soup = make_soup(response.text)
        return self.parse(response.text, soup, response.url)

    def parse(self, html: str, soup: BeautifulSoup, resolved_url: str) -> ExtractedContent:
        raise NotImplementedError

    def from_page(
        self,
        soup: BeautifulSoup,
        resolved_url: str,
        title: str | None = None,
        description: str | None = None,
        images: list[str] | None = None,
        videos: list[str] | None = None,
        content_type: str | None = None,
        include_meta_media: bool = True,
        raw: dict[str, Any] | None = None,
    ) -> ExtractedContent:
        meta_images = meta_values(soup, ("og:image", "twitter:image")) if include_meta_media else []
        meta_videos = meta_values(soup, ("og:video", "og:video:url", "twitter:player:stream")) if include_meta_media else []
        images = unique_urls((images or []) + meta_images)
        videos = unique_urls((videos or []) + meta_videos)
        title = clean_text(title) or first_meta(soup, ("og:title", "twitter:title")) or soup_title(soup)
        description = clean_text(description) or first_meta(soup, ("description", "og:description", "twitter:description"))
        cover = images[0] if images else None

        if content_type:
            resolved_content_type = content_type
        elif videos and images:
            resolved_content_type = "mixed"
        elif videos:
            resolved_content_type = "video"
        elif images:
            resolved_content_type = "image"
        else:
            resolved_content_type = "unknown"

        return ExtractedContent(
            platform=self.platform,
            url=self.url,
            resolved_url=resolved_url,
            content_type=resolved_content_type,
            title=title,
            description=description,
            images=images,
            videos=videos,
            cover=cover,
            raw=raw or {},
        )


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = unescape(str(value)).strip()
    return re.sub(r"\s+", " ", text) or None


def make_soup(html: str):
    if BeautifulSoup is not None:
        return BeautifulSoup(html, "html.parser")
    return MiniSoup(html)


class MiniTag:
    def __init__(self, attrs: dict[str, str] | None = None, text: str | None = None):
        self.attrs = attrs or {}
        self.string = text

    def get(self, key: str, default=None):
        return self.attrs.get(key, default)


class MiniSoup:
    def __init__(self, html: str):
        self.html = html
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
        self.title = MiniTag(text=clean_text(title_match.group(1))) if title_match else None

    def find_all(self, tag_name: str):
        if tag_name.lower() != "meta":
            return []
        tags = []
        for match in re.finditer(r"<meta\b([^>]*)>", self.html, flags=re.I | re.S):
            tags.append(MiniTag(_parse_attrs(match.group(1))))
        return tags

    def find(self, tag_name: str, id: str | None = None):
        if tag_name.lower() != "script" or not id:
            return None
        pattern = rf"<script\b(?=[^>]*\bid=[\"']?{re.escape(id)}[\"']?)[^>]*>(.*?)</script>"
        match = re.search(pattern, self.html, flags=re.I | re.S)
        return MiniTag({"id": id}, match.group(1)) if match else None


def _parse_attrs(raw_attrs: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", raw_attrs, flags=re.S):
        attrs[match.group(1)] = unescape(match.group(3))
    return attrs


def unique_urls(urls: list[str]) -> list[str]:
    result = []
    seen = set()
    for url in urls:
        if not isinstance(url, str):
            continue
        url = unescape(url).strip()
        if not url or url in seen or not re.match(r"https?://", url):
            continue
        seen.add(url)
        result.append(url)
    return result


def soup_title(soup: BeautifulSoup) -> str | None:
    return clean_text(soup.title.string) if soup.title and soup.title.string else None


def meta_values(soup: BeautifulSoup, names: tuple[str, ...]) -> list[str]:
    values = []
    for name in names:
        for tag in soup.find_all("meta"):
            if tag.get("property") == name or tag.get("name") == name:
                content = tag.get("content")
                if content:
                    values.append(content)
    return values


def first_meta(soup: BeautifulSoup, names: tuple[str, ...]) -> str | None:
    for value in meta_values(soup, names):
        if text := clean_text(value):
            return text
    return None


def extract_json_assignment(html: str, variable_name: str) -> dict[str, Any]:
    marker = re.escape(variable_name)
    match = re.search(rf"{marker}\s*=\s*({{.*?}})\s*;?\s*</script", html, flags=re.S)
    if not match:
        return {}
    return parse_json_like(match.group(1))


def extract_json_script_by_id(soup: BeautifulSoup, script_id: str) -> dict[str, Any]:
    tag = soup.find("script", id=script_id)
    if not tag:
        return {}
    text = (tag.string or tag.get_text() or "").strip()
    if not text:
        return {}
    for candidate in (text, unquote(text)):
        parsed = parse_json_like(candidate)
        if parsed:
            return parsed
    return {}


def parse_json_like(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    replacements = {
        ":undefined": ":null",
        ": undefined": ": null",
        ":void 0": ":null",
        ": void 0": ": null",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def collect_urls(value: Any, pattern: str | None = None) -> list[str]:
    urls: list[str] = []
    compiled = re.compile(pattern) if pattern else None

    def visit(node: Any):
        if isinstance(node, str):
            if re.match(r"https?://", node) and (compiled is None or compiled.search(node)):
                urls.append(node)
        elif isinstance(node, dict):
            for item in node.values():
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    return unique_urls(urls)


def collect_urls_from_text(text: str, pattern: str | None = None) -> list[str]:
    normalized = normalize_escaped_text(text)
    urls = re.findall(r"https?://[^\"'<>\s\\)]+", normalized)
    return unique_urls([url for url in urls if not pattern or re.search(pattern, url)])


def collect_relative_ufile_urls(text: str, base_urls: list[str]) -> list[str]:
    if not base_urls:
        return []
    parsed = urlparse(base_urls[0])
    if not parsed.scheme or not parsed.netloc:
        return []
    host = f"{parsed.scheme}://{parsed.netloc}"
    normalized = normalize_escaped_text(text)
    paths = re.findall(r"(/ufile/atlas/[^\"'<>\s\\]+\.(?:jpe?g|png|webp))", normalized, flags=re.I)
    urls = []
    seen_media = set()
    for path in paths:
        media_key = re.sub(r"\.(?:jpe?g|png|webp)$", "", path, flags=re.I)
        if media_key in seen_media:
            continue
        seen_media.add(media_key)
        urls.append(f"{host}{path}")
    return unique_urls(urls)


def img_srcs_by_class(html: str, class_name: str) -> list[str]:
    srcs = []
    for match in re.finditer(r"<img\b([^>]*)>", html, flags=re.I | re.S):
        attrs = _parse_attrs(match.group(1))
        classes = attrs.get("class", "")
        if class_name not in classes.split():
            continue
        src = attrs.get("src")
        if src:
            srcs.append(src)
    return unique_urls(srcs)


def normalize_escaped_text(text: str) -> str:
    text = unescape(text)
    text = text.replace("\\u002F", "/").replace("\\/", "/")
    text = text.replace("\\u0026", "&")
    return text


def first_quoted_value_from_text(text: str, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        pattern = rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"'
        match = re.search(pattern, text, flags=re.S)
        if not match:
            continue
        try:
            value = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            value = match.group(1).replace("\\n", "\n")
        if cleaned := clean_text(value):
            return cleaned
    return None


def first_string_from_keys(value: Any, keys: tuple[str, ...]) -> str | None:
    for item in walk_dicts(value):
        for key in keys:
            text = clean_text(item.get(key))
            if text:
                return text
    return None
