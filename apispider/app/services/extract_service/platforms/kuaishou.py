from app.services.extract_service.platforms.base import (
    BaseExtractor,
    collect_relative_ufile_urls,
    collect_urls,
    collect_urls_from_text,
    extract_json_assignment,
    first_quoted_value_from_text,
    first_string_from_keys,
    unique_urls,
)


class Kuaishou(BaseExtractor):
    platform = "kuaishou"

    def parse(self, html, soup, resolved_url):
        apollo_state = extract_json_assignment(html, "window.__APOLLO_STATE__")
        title = (
            first_string_from_keys(apollo_state, ("caption", "title", "desc", "description"))
            or first_quoted_value_from_text(html, ("caption", "title", "desc", "description"))
        )
        description = (
            first_string_from_keys(apollo_state, ("caption", "desc", "description"))
            or first_quoted_value_from_text(html, ("caption", "desc", "description"))
        )
        images = kuaishou_images(apollo_state, html)
        videos = collect_urls(apollo_state, r"\.(?:mp4|m3u8)(?:\?|$)|video|photoUrl|play")
        videos.extend(collect_urls_from_text(html, r"\.(?:mp4|m3u8)(?:\?|$)"))

        return self.from_page(
            soup,
            resolved_url,
            title=title,
            description=description,
            images=images,
            videos=videos[:1],
            content_type="video" if videos else ("image" if images else None),
            include_meta_media=False,
            raw={"apollo_state_found": bool(apollo_state)},
        )


def kuaishou_images(apollo_state, html):
    cover_candidates = collect_urls(apollo_state, r"\.(?:jpe?g|png|webp)(?:\?|$)|image|cover")
    cover_candidates.extend(collect_urls_from_text(html, r"(?:yximgs|gifshow)\.com/.+\.(?:jpe?g|png|webp)(?:\?|$)"))
    cover_candidates = [
        url for url in cover_candidates
        if "/uhead/" not in url and "/bs2/ost/" not in url
    ]
    atlas_images = collect_relative_ufile_urls(html, cover_candidates)
    if atlas_images:
        return atlas_images
    return unique_urls(cover_candidates)
