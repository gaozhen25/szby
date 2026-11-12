"""Authentication for Boss Zhipin.

Credentials come from the Adapter-managed SQLite vault or ``BOSS_COOKIES``.
Interactive login uses an Adapter-managed Chrome profile and never reads a user profile.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

from message_adapter.config import AdapterConfig
from message_adapter.storage import CredentialStore

from .constants import (
    AUTH_HEALTH_CACHE_TTL_S,
    SESSION_COOKIES,
)

logger = logging.getLogger(__name__)

# Credential TTL: warn and attempt refresh after 7 days
CREDENTIAL_TTL_DAYS = 7
_CREDENTIAL_TTL_SECONDS = CREDENTIAL_TTL_DAYS * 86400

_AUTH_HEALTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


# ── Credential data class ───────────────────────────────────────────


class Credential:
    """Holds Boss Zhipin session cookies."""

    def __init__(self, cookies: dict[str, str], browser_profile: str = ""):
        self.cookies = cookies
        self.browser_profile = browser_profile

    @property
    def is_valid(self) -> bool:
        return bool(self.cookies)

    @property
    def missing_session_cookies(self) -> list[str]:
        return sorted(SESSION_COOKIES - set(self.cookies))

    @property
    def has_session_cookies(self) -> bool:
        """QR login only needs wt2 + zp_at for chat and profile."""
        return not self.missing_session_cookies

    def to_dict(self) -> dict[str, Any]:
        return {
            "cookies": self.cookies,
            "browser_profile": self.browser_profile,
            "saved_at": time.time(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Credential:
        return cls(
            cookies=data.get("cookies", {}),
            browser_profile=str(data.get("browser_profile") or ""),
        )

    def as_cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())


# ── Credential persistence ──────────────────────────────────────────


def _store_or_default(store: CredentialStore | None) -> tuple[CredentialStore, bool]:
    if store is not None:
        return store, False
    path = AdapterConfig.load(platform="boss").credential_db
    return CredentialStore(path), True


def save_credential(
    credential: Credential,
    *,
    store: CredentialStore | None = None,
    platform_actor_id: str = "",
) -> None:
    """Persist the one BOSS credential assigned to this device."""
    target, owned = _store_or_default(store)
    try:
        target.save("boss", credential.to_dict(), platform_actor_id=platform_actor_id)
    finally:
        if owned:
            target.close()


def load_credential(
    *,
    store: CredentialStore | None = None,
) -> Credential | None:
    """Load one BOSS credential from SQLite."""
    target, owned = _store_or_default(store)
    try:
        data = target.get("boss")
        if not data:
            return None
        cred = Credential.from_dict(data)
        if not cred.is_valid:
            return None
        if not cred.has_session_cookies:
            missing = cred.missing_session_cookies
            logger.warning("Saved credential missing session cookies: %s", ", ".join(missing))
            if not target.read_only:
                clear_credential(store=target)
            return None
        saved_at = data.get("saved_at", 0)
        if saved_at and (time.time() - saved_at) > _CREDENTIAL_TTL_SECONDS:
            logger.info(
                "Using saved credential older than %d days; validity will be checked by the API",
                CREDENTIAL_TTL_DAYS,
            )
        return cred
    except (TypeError, KeyError) as e:
        logger.warning("Failed to load saved credential: %s", e)
        return None
    finally:
        if owned:
            target.close()


def clear_credential(*, store: CredentialStore | None = None) -> None:
    """Remove one saved BOSS credential."""
    target, owned = _store_or_default(store)
    try:
        target.delete("boss")
    finally:
        if owned:
            target.close()
    _AUTH_HEALTH_CACHE.clear()


# ── Environment variable fallback ───────────────────────────────────


def load_from_env() -> Credential | None:
    """Load cookies from BOSS_COOKIES environment variable.

    Format: "key1=val1; key2=val2; ..."
    """
    raw = os.environ.get("BOSS_COOKIES", "").strip()
    if not raw:
        return None
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            cookies[k] = v
    if not cookies:
        logger.debug("BOSS_COOKIES env set but no valid key=value pairs found")
        return None
    cred = Credential(cookies=cookies)
    logger.info("Loaded %d cookies from BOSS_COOKIES environment variable", len(cookies))
    return cred


# ── Unified get_credential ──────────────────────────────────────────


def get_credential(
    *,
    store: CredentialStore | None = None,
) -> Credential | None:
    """Load this device's BOSS credential.

    1. SQLite credential vault
    2. Environment variable (BOSS_COOKIES)
    """
    cred = load_credential(store=store)
    if cred:
        logger.info("Loaded BOSS device credential")
        return cred

    cred = load_from_env()
    if cred:
        logger.info("Loaded credential from BOSS_COOKIES env")
        if store is None or not store.read_only:
            save_credential(cred, store=store)
        return cred

    return None


def _credential_cache_key(credential: Credential) -> str:
    payload = json.dumps(sorted(credential.cookies.items()), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_credential_details(
    credential: Credential,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Verify that the credential can authenticate the BOSS message channel."""
    if not credential.has_session_cookies:
        missing = ", ".join(credential.missing_session_cookies)
        return {
            "authenticated": False,
            "messaging_authenticated": False,
            "reason": f"缺少登录 Cookie: {missing}",
        }

    from .client import BossClient
    from .exceptions import BossApiError

    cache_key = _credential_cache_key(credential)
    now = time.time()
    if not force_refresh:
        cached = _AUTH_HEALTH_CACHE.get(cache_key)
        if cached and (now - cached[0]) <= AUTH_HEALTH_CACHE_TTL_S:
            return dict(cached[1])

    error = ""
    authenticated = False
    with BossClient(credential, request_delay=0.2) as client:
        try:
            client.get_ws_auth()
            authenticated = True
        except BossApiError as exc:
            error = f"消息通道鉴权失败: {exc}"

    result: dict[str, Any] = {
        "authenticated": authenticated,
        "messaging_authenticated": authenticated,
    }
    if error:
        result["reason"] = error
    _AUTH_HEALTH_CACHE[cache_key] = (time.time(), dict(result))
    return result


def verify_credential(
    credential: Credential,
    *,
    force_refresh: bool = False,
) -> tuple[bool, str | None]:
    """Verify that the credential can access an authenticated API."""
    result = verify_credential_details(credential, force_refresh=force_refresh)
    return result["authenticated"], result.get("reason")
