"""爆款参考内容筛选：双平台各半、各自按点赞；单平台按点赞凑满。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, TypeVar

_ContentItem = TypeVar("_ContentItem")

_DOUYIN_ALIASES = frozenset({"抖音", "dy", "douyin"})
_XHS_ALIASES = frozenset({"小红书", "xhs", "xiaohongshu"})
_BALANCE_PLATFORM_CODES = ("dy", "xhs")

# 近 N 天优先（按平台）；过旧只作补充
FRESHNESS_DAYS = 180
FRESHNESS_DAYS_BY_PLATFORM = {
    "xhs": 180,  # 小红书：近半年
    "dy": 180,  # 抖音：近半年
}
XHS_SOFT_LIKES_MIN = 200
DY_SOFT_LIKES_PERCENTILE = 0.4

# 服务/咨询型账号：压掉纯生活向内容（全行业通用）
SERVICE_ACCOUNT_MARKERS = (
    "服务",
    "咨询",
    "机构",
    "中介",
    "顾问",
    "申请",
    "获客",
    "转化",
    "陪玩",
    "代练",
    "培训",
    "辅导",
    "代理",
    "加盟",
)
# 账号本身就是生活/探店内容号时，不做生活向打压
LIFESTYLE_AS_CORE_MARKERS = (
    "探店",
    "本地生活",
    "美食探店",
    "穿搭",
    "旅拍",
    "生活记录",
    "日常分享",
    "vlog博主",
)
SERVICE_INTENT_MARKERS = (
    "咨询",
    "服务",
    "测评",
    "教程",
    "教学",
    "种草",
    "避坑",
    "避雷",
    "干货",
    "宝典",
    "攻略",
    "机构",
    "报价",
    "套餐",
    "预约",
    "对比",
    "怎么选",
    "哪家好",
    "申请",
    "规划",
    "方案",
    "陪跑",
    "一对一",
    "顾问",
    "中介",
    "文书",
    "录取",
    "签证",
    "选校",
    "网申",
    "背景提升",
    "offer",
    "Offer",
    "跟练",
    "陪玩",
    "上分",
    "代练",
    "课程",
    "报名",
    "落地",
    "交付",
)
LIFESTYLE_OFFTOPIC_MARKERS = (
    "日常vlog",
    "一日吃",
    "周末去哪",
    "城市漫步",
    "穿搭日常",
    "探店打卡",
    "逛街",
    "旅拍",
    "室友",
    "食堂",
    "宿舍日常",
    "留学生活",
    "留子日常",
    "留学日记",
    "留学vlog",
    "留子vlog",
    "在国外的日子",
    "出国后的日常",
    "留学生活记录",
    "吃饭日记",
    "今日份快乐",
    "碎片日常",
)
DEFAULT_SERVICE_LIFESTYLE_EXCLUDES = (
    "日常vlog",
    "穿搭日常",
    "周末去哪",
    "留学生活",
    "留子日常",
)
# 兼容旧名
DEFAULT_STUDY_ABROAD_SERVICE_EXCLUDES = DEFAULT_SERVICE_LIFESTYLE_EXCLUDES
STUDY_ABROAD_MARKERS = ("留学", "出国留学", "海外升学", "国际本科", "中外合办")
STUDY_ABROAD_SERVICE_INTENT_MARKERS = SERVICE_INTENT_MARKERS
STUDY_ABROAD_LIFESTYLE_MARKERS = LIFESTYLE_OFFTOPIC_MARKERS



def freshness_days_for_item(item: Any) -> int:
    code = _item_platform(item)
    return int(FRESHNESS_DAYS_BY_PLATFORM.get(code, FRESHNESS_DAYS))


def _is_fresh(item: Any, *, within_days: int | None = None) -> bool:
    days = int(within_days) if within_days is not None else freshness_days_for_item(item)
    published = _parse_published_at(_item_published_at(item))
    if published is None:
        # 无时间字段时不当作过期，留给后续排序降权
        return True
    return published >= datetime.now(UTC) - timedelta(days=max(days, 1))


def _platform_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _DOUYIN_ALIASES:
        return "dy"
    if text in _XHS_ALIASES:
        return "xhs"
    return text


def account_has_douyin(platforms: Sequence[str] | None) -> bool:
    return any(_platform_code(item) == "dy" for item in (platforms or []))


def account_has_xiaohongshu(platforms: Sequence[str] | None) -> bool:
    return any(_platform_code(item) == "xhs" for item in (platforms or []))


def resolve_hot_content_type_targets(
    platforms: Sequence[str] | None,
    *,
    limit: int = 8,
) -> tuple[int, int]:
    """兼容旧调用：返回 (limit, 0)。双平台配额见 ``platform_quotas``。"""

    if limit <= 0:
        return 0, 0
    return limit, 0


def platform_quotas(
    platforms: Sequence[str] | None,
    *,
    limit: int,
    available_codes: Sequence[str] | None = None,
) -> dict[str, int]:
    """双平台各约占一半；仅一边有候选时该边拿满额。"""

    if limit <= 0:
        return {}
    requested = [
        code
        for code in dict.fromkeys(_platform_code(item) for item in (platforms or []))
        if code in _BALANCE_PLATFORM_CODES
    ]
    available = {
        code
        for code in (_platform_code(item) for item in (available_codes or []))
        if code in _BALANCE_PLATFORM_CODES
    }
    if requested and available:
        codes = [code for code in requested if code in available]
    elif requested:
        codes = list(requested)
    else:
        codes = [code for code in _BALANCE_PLATFORM_CODES if code in available]
        if not codes:
            codes = list(available)
    if not codes:
        return {}
    if len(codes) == 1:
        return {codes[0]: limit}
    # 稳定顺序：抖音、小红书；奇数限额时抖音多 1
    ordered = [code for code in _BALANCE_PLATFORM_CODES if code in codes]
    ordered.extend(code for code in codes if code not in ordered)
    base = limit // len(ordered)
    rem = limit % len(ordered)
    return {
        code: base + (1 if index < rem else 0) for index, code in enumerate(ordered)
    }


def _item_platform(item: Any) -> str:
    return _platform_code(
        getattr(item, "platform", None)
        or (item.get("platform") if isinstance(item, dict) else "")
    )


def _item_content_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("contentId") or item.get("content_id") or "").strip()
    return str(getattr(item, "content_id", "") or "").strip()


def _item_content_type(item: Any) -> str:
    if isinstance(item, dict):
        return (
            str(item.get("contentType") or item.get("content_type") or "unknown").strip()
            or "unknown"
        )
    return str(getattr(item, "content_type", "unknown") or "unknown").strip() or "unknown"


def _item_source_keyword(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("sourceKeyword") or item.get("source_keyword") or "").strip()
    return str(getattr(item, "source_keyword", "") or "").strip()


def _item_liked_count(item: Any) -> int:
    if isinstance(item, dict):
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        raw = item.get("likedCount")
        if raw is None:
            raw = item.get("liked_count")
        if raw is None and metrics:
            raw = metrics.get("likedCount", metrics.get("liked_count"))
    else:
        raw = getattr(item, "liked_count", 0)
    try:
        return max(int(raw or 0), 0)
    except (TypeError, ValueError):
        return 0


def _item_engagement_score(item: Any) -> float:
    if isinstance(item, dict):
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        raw = item.get("engagement_score")
        if raw is None:
            raw = item.get("engagementScore")
        if raw is None and metrics:
            raw = metrics.get("engagementScore", metrics.get("engagement_score"))
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(getattr(item, "engagement_score", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _rank_key(item: Any) -> tuple[int, float, str]:
    return (
        _item_liked_count(item),
        _item_engagement_score(item),
        _item_content_id(item),
    )


def _item_title(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("title") or "").strip()
    return str(getattr(item, "title", "") or "").strip()


def _item_summary(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("summary") or item.get("desc") or "").strip()
    return str(getattr(item, "summary", "") or "").strip()


def _item_published_at(item: Any) -> str:
    if isinstance(item, dict):
        return str(
            item.get("publishedAt")
            or item.get("published_at")
            or item.get("publish_time")
            or ""
        ).strip()
    return str(getattr(item, "published_at", "") or "").strip()


def _parse_published_at(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    # 纯时间戳
    if text.isdigit():
        try:
            ts = int(text)
            if ts > 10_000_000_000:
                ts = ts // 1000
            return datetime.fromtimestamp(ts, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _keyword_list(account_context: dict[str, Any] | None) -> list[str]:
    context = dict(account_context or {})
    pack = dict(context.get("keywordPack") or {})
    keywords = [
        str(item).strip()
        for item in (
            list(pack.get("core") or [])
            + list(pack.get("longTail") or pack.get("long_tail") or [])
            + list(context.get("keywords") or [])
        )
        if str(item or "").strip()
    ]
    return list(dict.fromkeys(keywords))


def _exclude_list(account_context: dict[str, Any] | None) -> list[str]:
    context = dict(account_context or {})
    pack = dict(context.get("keywordPack") or {})
    excludes = [
        str(item).strip()
        for item in (
            list(context.get("keywordExcludes") or [])
            + list(pack.get("excludes") or [])
        )
        if str(item or "").strip()
    ]
    if _account_needs_service_intent_filter(context):
        excludes = list(
            dict.fromkeys([*excludes, *DEFAULT_SERVICE_LIFESTYLE_EXCLUDES])
        )
    return excludes


def _account_blob(account_context: dict[str, Any] | None) -> str:
    context = dict(account_context or {})
    account = dict(context.get("account") or context)
    seed = dict(context.get("benchmarkSeed") or {})
    return " ".join(
        [
            str(account.get("productService") or ""),
            str(account.get("industry") or ""),
            str(account.get("description") or ""),
            str(account.get("purpose") or ""),
            str(seed.get("description") or ""),
            str(seed.get("bio") or ""),
            str(seed.get("name") or ""),
        ]
    )


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    blob = str(text or "")
    if not blob:
        return False
    return any(marker and marker in blob for marker in markers)


def account_is_service_oriented(account_context: dict[str, Any] | None) -> bool:
    """定位里带咨询/服务/机构等，且不是以探店生活本身为产品。"""

    blob = _account_blob(account_context)
    if not _contains_any(blob, SERVICE_ACCOUNT_MARKERS):
        return False
    if _contains_any(blob, LIFESTYLE_AS_CORE_MARKERS) and not _contains_any(
        blob, ("咨询", "服务", "机构", "中介", "顾问", "获客", "转化", "培训", "辅导")
    ):
        return False
    return True


def _account_needs_service_intent_filter(
    account_context: dict[str, Any] | None,
) -> bool:
    return account_is_service_oriented(account_context)


def _account_is_study_abroad_service(account_context: dict[str, Any] | None) -> bool:
    """兼容旧调用；现已并入全行业服务意图过滤。"""

    blob = _account_blob(account_context)
    return account_is_service_oriented(account_context) and _contains_any(
        blob, STUDY_ABROAD_MARKERS
    )


def _item_text_blob(item: Any) -> str:
    return f"{_item_title(item)} {_item_summary(item)} {_item_source_keyword(item)}"


def _item_has_service_intent(item: Any) -> bool:
    return _contains_any(_item_text_blob(item), SERVICE_INTENT_MARKERS)


def _item_is_lifestyle_offtopic(item: Any) -> bool:
    """生活向且无服务信号 → 对服务型账号视为跑偏。"""

    blob = _item_text_blob(item)
    if not _contains_any(blob, LIFESTYLE_OFFTOPIC_MARKERS):
        return False
    return not _item_has_service_intent(item)


def _keyword_tokens(keyword: str) -> set[str]:
    text = str(keyword or "").strip().lower()
    if len(text) < 2:
        return set()
    parts = {text}
    if len(text) >= 4:
        parts.add(text[:2])
        parts.add(text[-2:])
        parts.add(text[2:4] if len(text) >= 4 else text)
    return {part for part in parts if len(part) >= 2}


def _body_has_keyword(title: str, summary: str, keywords: Sequence[str]) -> bool:
    blob = f"{title} {summary}".lower()
    title_l = title.lower()
    summary_l = summary.lower()
    for raw in keywords:
        keyword = str(raw or "").strip().lower()
        if len(keyword) < 2:
            continue
        if keyword in summary_l:
            return True
        if keyword in title_l:
            if not summary_l:
                continue
            # 标题命中且摘要与关键词有字面/片段重合 → 主题相关
            tokens = _keyword_tokens(keyword)
            if any(token in summary_l for token in tokens):
                return True
        if keyword in blob and summary_l and keyword in summary_l:
            return True
    return False


def _is_title_bait(item: Any, keywords: Sequence[str]) -> bool:
    """标题蹭词但正文/摘要不围绕主题 → 标题党。

    摘要里已有服务意图（咨询/避坑/怎么选等）时不判标题党，避免误杀服务向爆款。
    """

    summary = _item_summary(item)
    if summary and _contains_any(summary, SERVICE_INTENT_MARKERS):
        return False
    title = _item_title(item)
    if not title or not keywords:
        return False
    title_l = title.lower()
    summary_l = summary.lower()
    hit_in_title = False
    for raw in keywords:
        keyword = str(raw or "").strip().lower()
        if len(keyword) < 2:
            continue
        if keyword in title_l:
            hit_in_title = True
            if keyword in summary_l:
                return False
            tokens = _keyword_tokens(keyword)
            if summary_l and any(token in summary_l for token in tokens):
                return False
    if not hit_in_title:
        return False
    if not summary_l:
        # 采集常无摘要：标题已含检索词时不当标题党，否则首批几乎筛空、只能空转翻页
        return False
    return not _body_has_keyword(title, summary, keywords)


def _soft_viral_ok(item: Any, *, pool_likes: Sequence[int]) -> bool:
    likes = _item_liked_count(item)
    code = _item_platform(item)
    if code == "xhs":
        if likes >= XHS_SOFT_LIKES_MIN:
            return True
        if pool_likes:
            return likes >= float(median(pool_likes))
        return likes > 0
    if code == "dy":
        if not pool_likes:
            return likes > 0
        ordered = sorted(int(v) for v in pool_likes)
        index = max(0, int(len(ordered) * DY_SOFT_LIKES_PERCENTILE) - 1)
        return likes >= ordered[index]
    return likes > 0


def filter_strong_related_contents(
    candidates: Sequence[_ContentItem],
    *,
    account_context: dict[str, Any] | None = None,
    prefer_fresh_days: int | None = None,
) -> list[_ContentItem]:
    """强相关粗筛：排除词、去标题党、按平台时效优先、软爆款门槛。

    小红书/抖音均近半年优先；过旧仅作补充。有定位词时不回填无关内容。
    """

    pool = list(candidates or [])
    if not pool:
        return []

    from app.services.account_report.generation.keywords import text_hits_excludes

    keywords = _keyword_list(account_context)
    excludes = _exclude_list(account_context)

    after_exclude: list[_ContentItem] = []
    for item in pool:
        blob = f"{_item_title(item)} {_item_summary(item)} {_item_source_keyword(item)}"
        if text_hits_excludes(blob, excludes):
            continue
        after_exclude.append(item)
    if not after_exclude:
        after_exclude = list(pool)

    # 服务/咨询型账号（全行业）：丢掉纯生活向
    if _account_needs_service_intent_filter(account_context):
        lifestyle_filtered = [
            item
            for item in after_exclude
            if not _item_is_lifestyle_offtopic(item)
        ]
        if lifestyle_filtered:
            after_exclude = lifestyle_filtered

    after_bait = [
        item
        for item in after_exclude
        if not (keywords and _is_title_bait(item, keywords))
    ]
    if not after_bait:
        after_bait = list(after_exclude)

    # 有关键词时：标题/摘要含词，或本身就是该检索词召回的内容
    if keywords:
        keyword_set = {
            str(kw or "").strip().lower()
            for kw in keywords
            if len(str(kw or "").strip()) >= 2
        }
        related = [
            item
            for item in after_bait
            if not _is_title_bait(item, keywords)
            and (
                _body_has_keyword(_item_title(item), _item_summary(item), keywords)
                or any(
                    kw in _item_title(item).lower()
                    or kw in _item_summary(item).lower()
                    for kw in keyword_set
                )
                or _item_source_keyword(item).strip().lower() in keyword_set
            )
        ]
        after_bait = related

    # 服务型账号：服务意图优先排序，不足时回填其他非生活向相关内容（避免只剩 1–2 条）
    if _account_needs_service_intent_filter(account_context):
        service_hits = [item for item in after_bait if _item_has_service_intent(item)]
        if service_hits:
            rest = [
                item for item in after_bait if not _item_has_service_intent(item)
            ]
            after_bait = service_hits + rest

    likes_by_platform: dict[str, list[int]] = {}
    for item in after_bait:
        likes_by_platform.setdefault(_item_platform(item), []).append(
            _item_liked_count(item)
        )
    after_viral = [
        item
        for item in after_bait
        if _soft_viral_ok(
            item, pool_likes=likes_by_platform.get(_item_platform(item)) or []
        )
    ]
    if not after_viral:
        after_viral = list(after_bait)
    elif len(after_viral) < 8 and len(after_bait) > len(after_viral):
        # 软门槛过严导致凑不满 8：保留已过相关/生活向过滤的条目，避免无意义翻页
        after_viral = list(after_bait)

    fresh = [
        item
        for item in after_viral
        if _is_fresh(item, within_days=prefer_fresh_days)
    ]
    stale = [item for item in after_viral if item not in fresh]
    # 平台时效窗口内优先；不足时用过旧补充。有定位词时不回填无关内容。
    ordered = fresh + stale
    if keywords:
        return ordered
    return ordered if ordered else list(pool)


def content_exclusion_key(item: Any) -> tuple[str, str] | None:
    platform = _item_platform(item)
    content_id = _item_content_id(item)
    if not platform or not content_id:
        return None
    return platform, content_id


KOUBO_TAG = "口播"
HOT_CONTENTS_PER_KEYWORD = 2
HOT_CONTENTS_DEFAULT_LIMIT = 8


def is_koubo_video(item: Any, *, detected: bool | None = None) -> bool:
    """仅当模型检出前 3 秒人像（或显式 detected=True）时视为口播。"""

    if detected is False:
        return False
    if detected is True:
        return _item_content_type(item) == "video" and _item_platform(item) == "dy"
    tags = []
    if isinstance(item, dict):
        tags = [str(tag).strip() for tag in (item.get("tags") or []) if str(tag or "").strip()]
    else:
        tags = [
            str(tag).strip()
            for tag in (getattr(item, "tags", None) or [])
            if str(tag or "").strip()
        ]
    return (
        KOUBO_TAG in tags
        and _item_content_type(item) == "video"
        and _item_platform(item) == "dy"
    )


def koubo_tags_for_item(
    item: Any,
    existing: Sequence[str] | None = None,
    *,
    detected: bool | None = None,
) -> list[str]:
    tags = [str(tag).strip() for tag in (existing or []) if str(tag or "").strip()]
    tags = [tag for tag in tags if tag != KOUBO_TAG]
    if is_koubo_video(item, detected=detected):
        tags.append(KOUBO_TAG)
    elif detected is True and _item_content_type(item) == "video":
        tags.append(KOUBO_TAG)
    return tags


def _select_likes_within_pool(
    pool: Sequence[_ContentItem],
    *,
    limit: int,
    per_keyword: int,
    selected_keys: set[tuple[str, str]],
) -> tuple[list[_ContentItem], list[_ContentItem]]:
    """在单一池内：每词 Top N，再按点赞回填。"""

    if limit <= 0 or not pool:
        return [], list(pool)

    keyword_groups: dict[str, list[_ContentItem]] = {}
    for item in pool:
        keyword_groups.setdefault(_item_source_keyword(item), []).append(item)

    selected: list[_ContentItem] = []
    leftovers: list[_ContentItem] = []
    per_keyword_limit = max(int(per_keyword or 0), 0)
    local_keys = set(selected_keys)

    for keyword in sorted(keyword_groups):
        ranked = sorted(keyword_groups[keyword], key=_rank_key, reverse=True)
        take = ranked[:per_keyword_limit] if per_keyword_limit else []
        leftovers.extend(ranked[per_keyword_limit:] if per_keyword_limit else ranked)
        for item in take:
            if len(selected) >= limit:
                leftovers.append(item)
                continue
            key = content_exclusion_key(item)
            if key is not None and key in local_keys:
                leftovers.append(item)
                continue
            selected.append(item)
            if key is not None:
                local_keys.add(key)

    if len(selected) < limit:
        still: list[_ContentItem] = []
        for item in sorted(leftovers, key=_rank_key, reverse=True):
            if len(selected) >= limit:
                still.append(item)
                continue
            key = content_exclusion_key(item)
            if key is not None and key in local_keys:
                still.append(item)
                continue
            selected.append(item)
            if key is not None:
                local_keys.add(key)
        leftovers = still
    else:
        leftovers = [
            item
            for item in leftovers
            if (key := content_exclusion_key(item)) is None or key not in local_keys
        ]

    return selected[:limit], leftovers


def select_balanced_hot_contents(
    candidates: Sequence[_ContentItem],
    *,
    limit: int = HOT_CONTENTS_DEFAULT_LIMIT,
    target_per_type: int | None = None,
    video_target: int | None = None,
    image_target: int | None = None,
    platforms: Sequence[str] | None = None,
    exclude_keys: set[tuple[str, str]] | frozenset[tuple[str, str]] | None = None,
    account_context: dict[str, Any] | None = None,
    per_keyword: int = HOT_CONTENTS_PER_KEYWORD,
) -> list[_ContentItem]:
    """双平台各约占一半、各自按点赞；单平台按点赞凑满。可排除上一批。

    ``target_per_type`` / ``video_target`` / ``image_target`` 保留兼容。
    """

    del target_per_type, video_target, image_target

    if limit <= 0:
        return []

    from app.services.account_report.generation.keywords import filter_items_for_primary_game

    scoped = filter_items_for_primary_game(list(candidates), account_context)
    # 词包漏斗粗筛仅在有账号/词包上下文时启用，避免无上下文选型行为漂移
    if account_context:
        scoped = filter_strong_related_contents(scoped, account_context=account_context)
    excluded = exclude_keys or set()

    if excluded:
        primary = [
            item
            for item in scoped
            if (key := content_exclusion_key(item)) is None or key not in excluded
        ]
        # 换一批：有未用候选只用未用的；没有则返回空，由上层翻页补货，绝不回填旧批
        pool = primary
    else:
        pool = list(scoped)

    if not pool:
        return []

    available_codes = list(
        dict.fromkeys(
            code
            for item in pool
            if (code := _item_platform(item)) in _BALANCE_PLATFORM_CODES
        )
    )
    quotas = platform_quotas(
        platforms,
        limit=limit,
        available_codes=available_codes,
    )
    if not quotas:
        selected, _ = _select_likes_within_pool(
            pool,
            limit=limit,
            per_keyword=per_keyword,
            selected_keys=set(),
        )
        return sorted(selected, key=_rank_key, reverse=True)[:limit]

    # 账号声明的平台优先；未声明时按候选里实际出现的平台分
    target_codes = list(quotas.keys())
    by_platform: dict[str, list[_ContentItem]] = {code: [] for code in target_codes}
    others: list[_ContentItem] = []
    for item in pool:
        code = _item_platform(item)
        if code in by_platform:
            by_platform[code].append(item)
        else:
            others.append(item)

    selected: list[_ContentItem] = []
    selected_keys: set[tuple[str, str]] = set()
    leftovers: list[_ContentItem] = list(others)

    for code in target_codes:
        quota = int(quotas.get(code) or 0)
        taken, rest = _select_likes_within_pool(
            by_platform.get(code) or [],
            limit=quota,
            per_keyword=per_keyword,
            selected_keys=selected_keys,
        )
        for item in taken:
            key = content_exclusion_key(item)
            selected.append(item)
            if key is not None:
                selected_keys.add(key)
        leftovers.extend(rest)

    if len(selected) < limit:
        filler, _ = _select_likes_within_pool(
            leftovers,
            limit=limit - len(selected),
            per_keyword=0,
            selected_keys=selected_keys,
        )
        selected.extend(filler)

    return sorted(selected, key=_rank_key, reverse=True)[:limit]
