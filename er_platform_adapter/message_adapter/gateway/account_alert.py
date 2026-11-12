from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from message_adapter.config import _load_dotenv

# Refresh inside the account monitor's 120-second online timer.
ACCOUNT_ALERT_HEARTBEAT_SECONDS = 40
ACCOUNT_ALERT_SOURCE = "adapter"
ACCOUNT_ALERT_PLATFORMS = ("boss", "douyin", "rednote")


def account_alert_settings(dotenv: str) -> tuple[str, str]:
    file_values = _load_dotenv(Path(dotenv))
    url = (file_values.get("ACCOUNT_ALERT_URL") or os.environ.get("ACCOUNT_ALERT_URL") or "").strip()
    secret = (
        file_values.get("ACCOUNT_ALERT_INTERNAL_SECRET")
        or os.environ.get("ACCOUNT_ALERT_INTERNAL_SECRET")
        or ""
    ).strip()
    return url, secret


def online_alert_accounts(platforms: dict[str, Any]) -> list[dict[str, str]]:
    """Boss, Douyin, and rednote accounts whose local status is online."""
    accounts: list[dict[str, str]] = []
    for platform in ACCOUNT_ALERT_PLATFORMS:
        item = platforms.get(platform)
        if not isinstance(item, dict) or not item.get("online"):
            continue
        platform_id = str(item.get("platform_actor_id") or "")
        if platform_id:
            accounts.append({"platform": platform, "platform_id": platform_id})
    return accounts


def alert_transitions(
    reported_at: dict[tuple[str, str], float],
    current: tuple[tuple[str, str], ...],
    *,
    now: float,
    heartbeat_seconds: float = ACCOUNT_ALERT_HEARTBEAT_SECONDS,
) -> list[tuple[str, str, str]]:
    """Online on first sight and every heartbeat; offline when an account drops."""
    current_keys = set(current)
    actions: list[tuple[str, str, str]] = []
    for platform, platform_id in current:
        last_sent = reported_at.get((platform, platform_id))
        if last_sent is None or now - last_sent >= heartbeat_seconds:
            actions.append((platform, platform_id, "online"))
    for platform, platform_id in reported_at:
        if (platform, platform_id) not in current_keys:
            actions.append((platform, platform_id, "offline"))
    return actions


class AccountAlertClient:
    """Posts one account online or offline alert."""

    def __init__(
        self,
        url: str,
        secret: str,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self._transport = transport

    async def send(self, platform: str, platform_id: str, alert_type: str) -> None:
        if alert_type not in {"online", "offline"}:
            raise ValueError("alert_type must be online or offline")
        if platform not in ACCOUNT_ALERT_PLATFORMS:
            raise ValueError("platform must be boss, douyin, or rednote")
        if not platform_id:
            raise ValueError("platform_id is required")
        event_id = f"alert-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:12]}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Internal-Secret": self.secret,
            "operationID": f"account-alert-{uuid4().hex}",
        }
        body = {
            "event_id": event_id,
            "platform": platform,
            "platform_id": platform_id,
            "source_service": ACCOUNT_ALERT_SOURCE,
            "alert_type": alert_type,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                response = await client.post(self.url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"account alert connection failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"account alert failed HTTP {response.status_code}")
