from app.services.extract_service.platforms.base import (
    BaseExtractor,
    clean_text,
    collect_urls,
    extract_json_assignment,
    first_meta,
    soup_title,
    unique_urls,
    walk_dicts,
)


class Rednote(BaseExtractor):
    platform = "rednote"

    def parse(self, html, soup, resolved_url):
        state = extract_json_assignment(html, "window.__INITIAL_STATE__")
        note = rednote_note_card(state)
        title = clean_text(note.get("title")) if note else None
        description = (
            clean_text(note.get("desc") or note.get("description")) if note else None
        )
        if not title:
            title = normalize_rednote_page_title(
                first_meta(soup, ("og:title", "twitter:title")) or soup_title(soup)
            )
        images = rednote_images(state)
        images = [url for url in images if "sns-avatar" not in url]
        videos = rednote_videos(state)

        return self.from_page(
            soup,
            resolved_url,
            title=title,
            description=description,
            images=images,
            videos=videos,
            include_meta_media=False,
            raw={"initial_state_found": bool(state)},
        )


def rednote_note_card(state):
    """Prefer the note payload itself; ignore footer/search titles elsewhere in state."""
    for item in walk_dicts(state):
        note_id = item.get("noteId")
        if not isinstance(note_id, str) or not note_id.strip():
            continue
        if any(key in item for key in ("imageList", "desc", "video", "type")):
            return item
    return None


def normalize_rednote_page_title(title: str | None) -> str | None:
    text = clean_text(title)
    if not text:
        return None
    for suffix in (" - 小红书", "｜小红书", "| 小红书"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return text or None


def rednote_images(state):
    images = []
    for item in walk_dicts(state):
        image_list = item.get("imageList")
        if not isinstance(image_list, list):
            continue
        for image in image_list:
            if not isinstance(image, dict):
                continue
            url = rednote_best_image_url(image)
            if url:
                images.append(url)
    return unique_urls(images) or collect_urls(state, r"\.(?:jpe?g|png|webp)(?:\?|$)|xhscdn|sns-img")


_PREFERRED_IMAGE_SCENES = ("H5_DTL", "WB_DFT")


def rednote_best_image_url(image: dict) -> str | None:
    """Prefer detail/default quality over preview (!nd_prv_...) thumbnails."""
    for key in ("url", "urlDefault"):
        url = clean_text(image.get(key))
        if url and "!nd_prv_" not in url:
            return url

    preferred = rednote_detail_image_from_info_list(image)
    if preferred:
        return preferred

    for key in ("url", "urlDefault", "urlPre"):
        url = clean_text(image.get(key))
        if url:
            return url
    return None


def rednote_detail_image_from_info_list(image):
    info_list = image.get("infoList")
    if not isinstance(info_list, list):
        return None
    by_scene: dict[str, str] = {}
    fallback = None
    for info in info_list:
        if not isinstance(info, dict):
            continue
        url = clean_text(info.get("url"))
        if not url:
            continue
        scene = str(info.get("imageScene") or "")
        if scene:
            by_scene[scene] = url
        if "!nd_prv_" not in url:
            fallback = fallback or url
    for scene in _PREFERRED_IMAGE_SCENES:
        if scene in by_scene:
            return by_scene[scene]
    return fallback


def rednote_videos(state):
    videos = []
    for item in walk_dicts(state):
        for key in ("masterUrl", "url"):
            url = item.get(key)
            if isinstance(url, str) and ("sns-video" in url or url.endswith((".mp4", ".m3u8"))):
                videos.append(url)
                break
    return unique_urls(videos[:1])
