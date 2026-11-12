"""账号报告人工相似账号的身份、校验与合并规则。"""

from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit, urlunsplit


MAX_MANUAL_SIMILAR_ACCOUNTS = 20
SIMILAR_ACCOUNT_DOMAINS = {
    "小红书": ("xiaohongshu.com",),
    "抖音": ("douyin.com",),
    "快手": ("kuaishou.com", "kwai.com"),
}


def normalize_public_profile_url(platform: str, value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    hostname = (parsed.hostname or "").lower()
    allowed_domains = SIMILAR_ACCOUNT_DOMAINS.get(platform, ())
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or not any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)
    ):
        raise ValueError(f"请输入有效的{platform}公开账号主页 HTTPS 链接")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", ""))


def similar_account_key(item: dict[str, Any]) -> str:
    creator_hash = str(item.get("creatorHash") or "").strip()
    if creator_hash:
        return creator_hash
    profile_url = str(item.get("profileUrl") or "").strip()
    identity = profile_url.split("?", 1)[0].rstrip("/").lower()
    if not identity:
        identity = f"{item.get('platform', '')}|{item.get('name', '')}".strip().lower()
    return f"legacy_{sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def same_similar_account(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_url = str(left.get("profileUrl") or "").split("?", 1)[0].rstrip("/").lower()
    right_url = str(right.get("profileUrl") or "").split("?", 1)[0].rstrip("/").lower()
    if left_url and right_url:
        return left_url == right_url
    return (
        str(left.get("platform") or "").strip().lower(),
        str(left.get("name") or "").strip().lower(),
    ) == (
        str(right.get("platform") or "").strip().lower(),
        str(right.get("name") or "").strip().lower(),
    )


def effective_similar_accounts(record: Any) -> list[dict[str, Any]]:
    excluded = set(record.excluded_similar_account_keys or [])
    merged: list[dict[str, Any]] = []
    for item in [*(record.manual_similar_accounts or []), *(record.similar_accounts or [])]:
        candidate = dict(item)
        if similar_account_key(candidate) in excluded:
            continue
        if any(same_similar_account(candidate, existing) for existing in merged):
            continue
        merged.append(candidate)
        if len(merged) >= MAX_MANUAL_SIMILAR_ACCOUNTS:
            break
    return merged


def with_configuration_metadata(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    configuration_key = similar_account_key(normalized)
    normalized["configurationKey"] = configuration_key
    normalized["configurationSource"] = (
        "manual" if configuration_key.startswith("manual_") else "generated"
    )
    return normalized
