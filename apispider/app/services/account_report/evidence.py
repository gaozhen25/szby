"""将三个平台的爬取结果归一化为有限、脱敏的报告证据。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from math import log1p
from typing import Any

from app.services.mediaspider.models import CrawlResult
from app.services.mediaspider.vendor.user_hash import anonymize_user_id, mask_nickname

from .models import (
    AccountReportEvidence,
    CommentEvidence,
    ContentEvidence,
    CreatorEvidence,
    CurrentAccountEvidence,
    IndustryEvidence,
)

METRIC_MULTIPLIERS = {"万": 10_000, "亿": 100_000_000}
PLATFORM_ALIASES = {
    "xhs": "xhs",
    "小红书": "xhs",
    "dy": "dy",
    "douyin": "dy",
    "抖音": "dy",
    "ks": "ks",
    "kuaishou": "ks",
    "快手": "ks",
}
CONTENT_FIELDS = {
    "xhs": ("note_id", "note_url"),
    "dy": ("aweme_id", "aweme_url"),
    "ks": ("video_id", "video_url"),
}
_HASH_PATTERN = re.compile(r"^[0-9a-f]{16}$")
_METRIC_PATTERN = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([万亿]?)\s*\+?\s*$")
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_MENTION_PATTERN = re.compile(r"(?<!\w)@[\w.-]+")
_EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}"
)
_CN_ID_PATTERN = re.compile(r"(?<!\d)(?:\d{15}|\d{17}[\dXx])(?!\d)")
_LANDLINE_PATTERN = re.compile(
    r"(?<!\d)(?:\(0\d{2,3}\)[- ]?\d{7,8}|0\d{2,3}[- ]?\d{7,8}|"
    r"(?:400|800)[- ]?\d{3}[- ]?\d{4})(?!\d)"
)
_CONTACT_HANDLE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:qq\s*(?:号码|号)?|wechat|weixin|vx|wx)"
    r"\s*(?:(?:是|为)|[:：=])?\s*[A-Za-z0-9_-]{4,}\b|"
    r"微信\s*(?:号)?\s*(?:(?:是|为)|[:：=])?\s*[A-Za-z0-9_-]{4,}",
    re.IGNORECASE,
)
_CREDENTIAL_PATTERN = re.compile(
    r"\b(?:authorization\s*[:=]\s*bearer\s+\S+|bearer\s+\S+|"
    r"(?:cookie|cookies|token|session|access_token|refresh_token)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
_STRUCTURED_SENSITIVE_FIELD_PATTERN = re.compile(
    r'''["']?(?:authorization|cookie|cookies|token|session|access_token|refresh_token|'''
    r'''user_id|uid|sec_user_id)["']?\s*[:=]\s*["']?[^,\s}\]"']+["']?''',
    re.IGNORECASE,
)
MAX_COMMENTS_PER_CONTENT = 3
MAX_COMMENTS_PER_PLATFORM = 10
MAX_REPORT_COMMENTS = 20


def normalize_metric(value: Any) -> int:
    """将平台数字、数字字符串和中文数量单位转换为非负整数。"""

    if value is None:
        return 0
    if isinstance(value, (int, float, Decimal)):
        try:
            return max(0, int(value))
        except (ValueError, OverflowError):
            return 0
    text = str(value).strip().replace(",", "").replace("，", "")
    match = _METRIC_PATTERN.fullmatch(text)
    if not match:
        return 0
    try:
        number = Decimal(match.group(1))
    except InvalidOperation:
        return 0
    multiplier = METRIC_MULTIPLIERS.get(match.group(2), 1)
    return max(0, int(number * multiplier))


def _raw_id_hash(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return anonymize_user_id(text)


def _trusted_creator_hash(value: Any) -> str:
    """仅 creator_hash 来源且格式合法时，才信任它已完成脱敏。"""

    text = str(value or "").strip()
    if not text:
        return ""
    return text if _HASH_PATTERN.fullmatch(text) else anonymize_user_id(text)


def _creator_hash(raw: dict[str, Any]) -> str:
    if raw.get("creator_hash") not in (None, ""):
        return _trusted_creator_hash(raw["creator_hash"])
    return _raw_id_hash(_first(raw, "author_id", "user_id", "sec_user_id", "uid", "id"))


def _comment_text(raw: dict[str, Any]) -> str:
    value = _first(raw, "content", "text", "comment", "comment_text")
    if not isinstance(value, str):
        return ""
    text = value
    text = _URL_PATTERN.sub("[链接已移除]", text)
    text = _EMAIL_PATTERN.sub("[邮箱已脱敏]", text)
    text = _CN_ID_PATTERN.sub("[身份证已脱敏]", text)
    text = _PHONE_PATTERN.sub("[手机号已脱敏]", text)
    text = _LANDLINE_PATTERN.sub("[座机已脱敏]", text)
    text = _CONTACT_HANDLE_PATTERN.sub("[联系方式已脱敏]", text)
    text = _MENTION_PATTERN.sub("[账号已脱敏]", text)
    text = _CREDENTIAL_PATTERN.sub("[凭证已脱敏]", text)
    text = _STRUCTURED_SENSITIVE_FIELD_PATTERN.sub("[敏感字段已脱敏]", text)
    return " ".join(text.split())[:200]


def _comment_content_id(platform: str, raw: dict[str, Any]) -> str:
    id_field = CONTENT_FIELDS.get(platform, ("content_id", "public_url"))[0]
    return str(_first(raw, id_field, "content_id", "parent_content_id")).strip()


def _platform(value: str) -> str:
    return PLATFORM_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())


def _first(raw: dict[str, Any], *keys: str, default: Any = "") -> Any:
    return next((raw[key] for key in keys if raw.get(key) not in (None, "")), default)


def _published_at(raw: dict[str, Any]) -> str:
    value = _first(raw, "time", "create_time", "timestamp")
    return str(value) if value not in (None, "") else ""


def _content_type(platform: str, raw: dict[str, Any]) -> str:
    raw_type = str(_first(raw, "content_type", "type", "note_type")).strip().lower()
    if platform == "xhs":
        if raw_type in {"video", "视频"}:
            return "video"
        if raw_type in {"normal", "image", "images", "图文"}:
            return "image"
    if platform == "dy":
        if raw_type in {"image", "images", "note", "图文"} or raw.get("image_post_info") or raw.get("images"):
            return "image"
        return "video"
    if platform == "ks":
        return "video"
    return "unknown"


def _content(platform: str, raw: dict[str, Any]) -> ContentEvidence | None:
    fields = CONTENT_FIELDS.get(platform)
    if not fields:
        return None
    id_field, url_field = fields
    content_id = str(_first(raw, id_field, "content_id")).strip()
    if not content_id:
        return None
    liked = normalize_metric(_first(raw, "liked_count", "like_count"))
    collected = normalize_metric(_first(raw, "collected_count", "collect_count"))
    comments = normalize_metric(_first(raw, "comment_count", "comments_count"))
    shares = normalize_metric(_first(raw, "share_count", "shares_count"))
    creator_hash = _creator_hash(raw)
    return ContentEvidence(
        platform=platform,
        content_id=content_id,
        title=str(_first(raw, "title", "desc"))[:500],
        summary=str(_first(raw, "desc", "description"))[:1000],
        creator_hash=creator_hash,
        creator_name=mask_nickname(str(_first(raw, "nickname", "author_name")))[:100],
        creator_display_name=str(_first(raw, "display_name"))[:100],
        creator_profile_url=str(_first(raw, "profile_url"))[:1000],
        public_url=str(_first(raw, url_field, "public_url", "url")),
        cover_url=str(_first(raw, "cover_url", "cover", "image_url")),
        published_at=_published_at(raw),
        liked_count=liked,
        collected_count=collected,
        comment_count=comments,
        share_count=shares,
        view_count=normalize_metric(_first(raw, "view_count", "viewd_count", "play_count")),
        source_keyword=str(_first(raw, "source_keyword", "keyword"))[:100],
        engagement_score=liked + collected * 2 + comments * 3 + shares * 4,
        source_operation=str(_first(raw, "source_operation"))[:100],
        source_sort=str(_first(raw, "source_sort"))[:100],
        evidence_completeness=sum(
            bool(value)
            for value in (
                content_id,
                _first(raw, url_field, "public_url", "url"),
                _first(raw, "title", "desc"),
                creator_hash,
                _published_at(raw),
                _content_type(platform, raw) != "unknown",
            )
        )
        / 6,
        content_type=_content_type(platform, raw),
    )


def _creator(platform: str, raw: dict[str, Any]) -> CreatorEvidence | None:
    creator_hash = _creator_hash(raw)
    if not creator_hash:
        return None
    return CreatorEvidence(
        platform=platform,
        creator_hash=creator_hash,
        name=mask_nickname(str(_first(raw, "nickname", "name")))[:100],
        displayName=str(_first(raw, "display_name"))[:100],
        profileUrl=str(_first(raw, "profile_url"))[:1000],
        avatarUrl=str(_first(raw, "avatar_url", "avatar"))[:1000],
        fans_count=normalize_metric(_first(raw, "fans_count", "follower_count", "followers_count")),
        works_count=normalize_metric(_first(raw, "works_count", "aweme_count", "photo_count")),
        interaction_count=normalize_metric(_first(raw, "interaction_count", "liked_count")),
        hit_content_count=normalize_metric(_first(raw, "hit_content_count")),
        representative_contents=[
            str(value)[:500]
            for value in list(raw.get("representative_contents") or [])[:3]
            if str(value).strip()
        ],
        matched_queries=[
            str(value)[:100]
            for value in list(raw.get("matched_queries") or [])[:5]
            if str(value).strip()
        ],
        source_operations=[
            str(value)[:100]
            for value in list(raw.get("source_operations") or [])[:10]
            if str(value).strip()
        ],
        evidence_completeness=max(
            0.0, min(float(raw.get("evidence_completeness") or 0), 1.0)
        ),
    )


def _creator_rank(item: CreatorEvidence) -> tuple[float, int, int]:
    return (
        item.similarity_score,
        item.hit_content_count,
        item.interaction_count,
    )


def _normalize_results(
    values: Iterable[CrawlResult | dict[str, Any]],
) -> list[CrawlResult]:
    return [
        value if isinstance(value, CrawlResult) else CrawlResult.model_validate(value)
        for value in values
    ]


def _collect_records(
    results: list[CrawlResult],
    *,
    owner_hashes: set[str],
    exclude_owners: bool,
) -> tuple[dict[tuple[str, str], ContentEvidence], dict[tuple[str, str], CreatorEvidence]]:
    contents: dict[tuple[str, str], ContentEvidence] = {}
    creators: dict[tuple[str, str], CreatorEvidence] = {}

    for result in results:
        platform = _platform(result.platform)
        for raw in result.contents:
            item = _content(platform, raw)
            if item is None or (exclude_owners and item.creator_hash in owner_hashes):
                continue
            key = (platform, item.content_id)
            if key not in contents or item.engagement_score > contents[key].engagement_score:
                contents[key] = item
        for raw in result.creators:
            item = _creator(platform, raw)
            if item is None:
                continue
            if exclude_owners and item.creator_hash in owner_hashes:
                continue
            key = (platform, item.creator_hash)
            if key not in creators or _creator_rank(item) > _creator_rank(creators[key]):
                creators[key] = item
    return contents, creators


def _enrich_creators(
    creators: dict[tuple[str, str], CreatorEvidence],
    contents: dict[tuple[str, str], ContentEvidence],
    *,
    owner_hashes: set[str],
    exclude_owners: bool,
) -> list[CreatorEvidence]:
    creator_contents: dict[tuple[str, str], list[ContentEvidence]] = {}
    for item in contents.values():
        if not item.creator_hash:
            continue
        if exclude_owners and item.creator_hash in owner_hashes:
            continue
        key = (item.platform, item.creator_hash)
        creator_contents.setdefault(key, []).append(item)
        creators.setdefault(
            key,
            CreatorEvidence(
                platform=item.platform,
                creator_hash=item.creator_hash,
                name=item.creator_name,
                displayName=item.creator_display_name,
                profileUrl=item.creator_profile_url,
            ),
        )

    enriched: list[CreatorEvidence] = []
    for key, creator in creators.items():
        hits = sorted(
            creator_contents.get(key, []),
            key=lambda item: item.engagement_score,
            reverse=True,
        )
        enriched.append(
            creator.model_copy(
                update={
                    "hit_content_count": len(hits),
                    "representative_contents": (
                        [item.title or item.content_id for item in hits[:3]]
                        or creator.representative_contents
                    ),
                    "interaction_count": max(
                        creator.interaction_count,
                        sum(item.engagement_score for item in hits),
                    ),
                }
            )
        )
    return enriched


def _collect_comments(
    results: list[CrawlResult],
    known_contents: set[tuple[str, str]],
    *,
    per_content: dict[tuple[str, str], int],
    per_platform: dict[str, int],
    seen_comments: set[tuple[str, str, str]],
    remaining: int,
) -> list[CommentEvidence]:
    comments: list[CommentEvidence] = []

    for result in results:
        platform = _platform(result.platform)
        for raw in result.comments:
            content_id = _comment_content_id(platform, raw)
            text = _comment_text(raw)
            content_key = (platform, content_id)
            dedupe_key = (platform, content_id, text)
            if (
                not text
                or content_key not in known_contents
                or dedupe_key in seen_comments
                or per_content.get(content_key, 0) >= MAX_COMMENTS_PER_CONTENT
                or per_platform.get(platform, 0) >= MAX_COMMENTS_PER_PLATFORM
                or len(comments) >= remaining
            ):
                continue
            comments.append(
                CommentEvidence(
                    platform=platform,
                    content_id=content_id,
                    text=text,
                    liked_count=normalize_metric(_first(raw, "liked_count", "like_count")),
                )
            )
            seen_comments.add(dedupe_key)
            per_content[content_key] = per_content.get(content_key, 0) + 1
            per_platform[platform] = per_platform.get(platform, 0) + 1
    return comments


def _score_hot_contents(items: list[ContentEvidence]) -> list[ContentEvidence]:
    """只在同平台、同内容类型中计算热度分位数，避免跨平台绝对量比较。"""

    groups: dict[tuple[str, str], list[ContentEvidence]] = {}
    for item in items:
        groups.setdefault((item.platform, item.content_type), []).append(item)
    scored: list[ContentEvidence] = []
    for values in groups.values():
        ordered = sorted(values, key=lambda item: (item.engagement_score, item.content_id))
        denominator = max(len(ordered) - 1, 1)
        percentiles = {
            item.content_id: index / denominator for index, item in enumerate(ordered)
        }
        for item in values:
            relevance = 1.0 if item.source_keyword else 0.35
            source_bonus = 1.0 if item.source_operation.startswith("hot_") else 0.6
            score = (
                percentiles[item.content_id] * 0.60
                + relevance * 0.20
                + source_bonus * 0.10
                + item.evidence_completeness * 0.10
            )
            scored.append(item.model_copy(update={"hot_score": round(score, 6)}))
    return scored


def _score_similar_accounts(
    items: list[CreatorEvidence],
    current_profiles: list[CreatorEvidence],
) -> list[CreatorEvidence]:
    owner_followers = {
        item.platform: item.fans_count for item in current_profiles if item.fans_count > 0
    }
    scored: list[CreatorEvidence] = []
    for item in items:
        query_fit = min(len(item.matched_queries) / 3, 1.0)
        content_fit = min(item.hit_content_count / 3, 1.0)
        owner_count = owner_followers.get(item.platform)
        if owner_count and item.fans_count:
            scale_fit = max(
                0.0,
                1 - abs(log1p(item.fans_count) - log1p(owner_count)) / 6,
            )
        else:
            scale_fit = 0.5
        interaction_quality = min(log1p(item.interaction_count) / 16, 1.0)
        score = (
            query_fit * 0.30
            + content_fit * 0.25
            + scale_fit * 0.15
            + interaction_quality * 0.10
            + item.evidence_completeness * 0.20
        )
        scored.append(item.model_copy(update={"similarity_score": round(score, 6)}))
    return scored


def build_report_evidence(
    current_account_results: Iterable[CrawlResult | dict[str, Any]],
    industry_results: Iterable[CrawlResult | dict[str, Any]],
    own_creator_hashes: set[str],
) -> AccountReportEvidence:
    """分流当前账号与行业结果，并在进入 AI 前完成脱敏、排名和截断。"""

    current_results = _normalize_results(current_account_results)
    industry_result_list = _normalize_results(industry_results)
    owner_hashes = {
        _trusted_creator_hash(value) for value in own_creator_hashes if value
    }
    current_contents, current_creators = _collect_records(
        current_results,
        owner_hashes=owner_hashes,
        exclude_owners=False,
    )
    industry_contents, industry_creators = _collect_records(
        industry_result_list,
        owner_hashes=owner_hashes,
        exclude_owners=True,
    )
    current_profiles = _enrich_creators(
        current_creators,
        current_contents,
        owner_hashes=owner_hashes,
        exclude_owners=False,
    )
    industry_accounts = _score_similar_accounts(_enrich_creators(
        industry_creators,
        industry_contents,
        owner_hashes=owner_hashes,
        exclude_owners=True,
    ), current_profiles)

    per_content: dict[tuple[str, str], int] = {}
    per_platform: dict[str, int] = {}
    seen_comments: set[tuple[str, str, str]] = set()
    current_comments = _collect_comments(
        current_results,
        set(current_contents),
        per_content=per_content,
        per_platform=per_platform,
        seen_comments=seen_comments,
        remaining=MAX_REPORT_COMMENTS,
    )
    industry_comments = _collect_comments(
        industry_result_list,
        set(industry_contents),
        per_content=per_content,
        per_platform=per_platform,
        seen_comments=seen_comments,
        remaining=MAX_REPORT_COMMENTS - len(current_comments),
    )

    ranked_current_contents = sorted(
        current_contents.values(),
        key=lambda item: (item.engagement_score, item.liked_count, item.content_id),
        reverse=True,
    )[:20]
    ranked_industry_contents = sorted(
        _score_hot_contents(list(industry_contents.values())),
        key=lambda item: item.hot_score,
        reverse=True,
    )[:20]
    similar_accounts = sorted(industry_accounts, key=_creator_rank, reverse=True)[:20]
    top_bloggers = sorted(
        industry_accounts,
        key=lambda item: (item.fans_count, item.interaction_count, item.creator_hash),
        reverse=True,
    )[:10]
    return AccountReportEvidence(
        currentAccountEvidence=CurrentAccountEvidence(
            profiles=sorted(current_profiles, key=_creator_rank, reverse=True)[:4],
            contents=ranked_current_contents,
            comments=current_comments,
        ),
        industryEvidence=IndustryEvidence(
            hotContents=ranked_industry_contents,
            similarAccounts=similar_accounts,
            topBloggers=top_bloggers,
            comments=industry_comments,
        ),
        owner_hashes=sorted(owner_hashes),
    )
