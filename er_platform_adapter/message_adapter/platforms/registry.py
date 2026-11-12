from __future__ import annotations

from pathlib import Path

from message_adapter.browser_profiles import BrowserProfile
from message_adapter.core.platform import PlatformAdapter


def create_platform_adapter(
    platform: str,
    *,
    credentials=None,
    browser_profile_root: Path | None = None,
) -> PlatformAdapter:
    selected = str(platform or "").strip().lower()
    profile = BrowserProfile(browser_profile_root, selected) if browser_profile_root is not None else None
    if selected == "boss":
        from .boss import BossPlatformAdapter

        return BossPlatformAdapter(credentials=credentials, browser_profile=profile)
    if selected == "douyin":
        from .douyin import DouyinPlatformAdapter

        return DouyinPlatformAdapter(credentials=credentials)
    if selected == "rednote":
        from .rednote import RednotePlatformAdapter

        return RednotePlatformAdapter(credentials=credentials)
    raise ValueError(f"unsupported platform: {platform}")
