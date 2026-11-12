"""账号报告采集平台规划与当前账号身份识别。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.mediaspider.models import CrawlResult
from app.services.mediaspider.platform_resolver import resolve_creator_platform
from app.services.mediaspider.vendor.user_hash import anonymize_user_id

from .owner_identity import parse_planned_owner_id


@dataclass(frozen=True)
class CrawlPlan:
    platform_name: str
    platform_code: str
    creator_url: str
    account_handle: str = ""


PLATFORM_ALIASES = {
    "xhs": ("小红书", "xhs"),
    "小红书": ("小红书", "xhs"),
    "dy": ("抖音", "dy"),
    "douyin": ("抖音", "dy"),
    "抖音": ("抖音", "dy"),
    "ks": ("快手", "ks"),
    "kuaishou": ("快手", "ks"),
    "快手": ("快手", "ks"),
}
CRAWLABLE_PLATFORM_CODES = frozenset({"xhs", "dy"})
VIDEO_CHANNEL_ALIASES = {"视频号", "wechat_channels", "channels"}


def canonical_platform(value: Any) -> tuple[str, str] | None:
    return PLATFORM_ALIASES.get(str(value or "").strip().lower())


def _lookup_platform_value(mapping: dict[str, Any], name: str, code: str) -> str:
    for key, value in dict(mapping or {}).items():
        if canonical_platform(key) == (name, code):
            return str(value or "").strip()
    return ""


def _creator_url(links: dict[str, Any], name: str, code: str) -> str:
    return _lookup_platform_value(links, name, code)


def _account_handle(accounts: dict[str, Any], name: str, code: str) -> str:
    return _lookup_platform_value(accounts, name, code)


def build_crawl_plans(
    account: dict[str, Any],
    links: dict[str, Any],
    platform_accounts: dict[str, Any] | None = None,
) -> tuple[list[CrawlPlan], list[str]]:
    raw_platforms = account.get("platforms") or [account.get("platform")]
    accounts = dict(
        platform_accounts
        if platform_accounts is not None
        else (account.get("platformAccounts") or account.get("platform_accounts") or {})
    )
    plans: list[CrawlPlan] = []
    unsupported: list[str] = []
    seen: set[str] = set()
    for value in raw_platforms:
        raw = str(value or "").strip()
        canonical = canonical_platform(raw)
        if canonical is None:
            if raw.lower() not in VIDEO_CHANNEL_ALIASES:
                raise ValueError("账号包含不支持的平台配置")
            if "视频号" not in unsupported:
                unsupported.append("视频号")
            continue
        name, code = canonical
        if code in seen:
            continue
        seen.add(code)
        if code not in CRAWLABLE_PLATFORM_CODES:
            if name not in unsupported:
                unsupported.append(name)
            continue
        plans.append(
            CrawlPlan(
                name,
                code,
                _creator_url(links, name, code),
                _account_handle(accounts, name, code),
            )
        )
    return plans, unsupported


def owner_identifiers(result: CrawlResult) -> set[str]:
    values: set[str] = set()
    for item in result.creators:
        for key in ("creator_hash", "author_id", "user_id", "sec_user_id", "uid", "id"):
            value = str(item.get(key) or "").strip()
            if value:
                values.add(value)
                break
    for item in result.contents:
        for key in ("creator_hash", "author_id", "user_id", "sec_user_id", "uid"):
            value = str(item.get(key) or "").strip()
            if value:
                values.add(value)
                break
    return values


def owner_identifiers_from_plan(plan: CrawlPlan) -> set[str]:
    """仅从平台已校验主页解析稳定 ID，不使用易重名的展示名称。"""

    if not plan.creator_url:
        return set()
    try:
        if resolve_creator_platform(plan.creator_url) != plan.platform_code:
            return set()
        owner_id = parse_planned_owner_id(plan.platform_code, plan.creator_url)
    except Exception:
        return set()
    return {anonymize_user_id(owner_id)} if owner_id else set()
