from __future__ import annotations

from collections.abc import Callable
import os
from typing import Any

from message_adapter.async_tools import run_in_daemon_thread
from message_adapter.browser_profiles import BrowserProfile
from message_adapter.config import AdapterConfig
from message_adapter.storage import CredentialStore, inspect_actor_binding


StatusCallback = Callable[[str], None]

_BROWSER_LOGIN_PLATFORMS = frozenset({"boss", "douyin", "rednote"})
# Pre-rename Rednote slot; purge alongside rednote so stale cookies cannot linger.
_LEGACY_CREDENTIAL_ALIASES = {
    "rednote": ("xiaohongshu",),
}


def credential_available(config: AdapterConfig) -> bool:
    """Check whether a platform can authenticate without exposing its credential."""
    environment_name = {"boss": "BOSS_COOKIES", "douyin": "DY_COOKIE", "rednote": "REDNOTE_COOKIE"}.get(config.platform, "")
    if environment_name and os.environ.get(environment_name, "").strip():
        return True
    store = CredentialStore(config.credential_db, read_only=True)
    try:
        return store.get(config.platform) is not None
    finally:
        store.close()


def credential_actor_id(config: AdapterConfig) -> str:
    store = CredentialStore(config.credential_db, read_only=True)
    try:
        return store.get_bound_actor_id(config.platform)
    finally:
        store.close()


def _ensure_uid_matches_state(config: AdapterConfig, platform_actor_id: str) -> None:
    bound_uid = inspect_actor_binding(config.state_db, config.platform)
    if bound_uid and bound_uid != platform_actor_id:
        raise RuntimeError(
            f"本机 {config.platform} 槽位已绑定另一个平台 UID；请先归档并重置该平台"
        )


def _validate_scanned_uid(
    config: AdapterConfig,
    profile: BrowserProfile,
    platform_actor_id: str,
) -> None:
    try:
        _ensure_uid_matches_state(config, platform_actor_id)
    except Exception:
        # Do not leave a rejected account authenticated in the managed profile.
        profile.clear()
        raise


def purge_browser_credentials(
    platform: str,
    config: AdapterConfig,
) -> bool:
    """Delete vault credentials and managed Chrome profiles for one browser platform.

    The UID-bound delivery state is intentionally preserved. Switching to another
    UID must go through the recoverable reset/archive flow.
    """
    selected = str(platform or "").strip().lower()
    removed = False
    store = CredentialStore(config.credential_db)
    try:
        removed = store.delete(selected) or removed
        for alias in _LEGACY_CREDENTIAL_ALIASES.get(selected, ()):
            removed = store.delete(alias) or removed
    finally:
        store.close()
    if selected in _BROWSER_LOGIN_PLATFORMS:
        BrowserProfile(config.browser_profile_root, selected).clear()
        for alias in _LEGACY_CREDENTIAL_ALIASES.get(selected, ()):
            BrowserProfile(config.browser_profile_root, alias).clear()
    return removed


async def login_platform(
    platform: str,
    config: AdapterConfig,
    on_status: StatusCallback,
) -> dict[str, str]:
    """Run one interactive QR login and persist the resulting platform UID."""
    selected = str(platform or "").strip().lower()
    if selected not in _BROWSER_LOGIN_PLATFORMS or selected != config.platform:
        raise ValueError("unsupported platform login")
    profile = BrowserProfile(config.browser_profile_root, selected)
    on_status("正在清除本机旧凭证")
    purge_browser_credentials(selected, config)
    store = CredentialStore(config.credential_db)
    try:
        if selected == "boss":
            from message_adapter.platforms.boss.auth import save_credential, verify_credential_details
            from message_adapter.platforms.boss.browser import login_with_profile
            from message_adapter.platforms.boss.client import BossClient

            # login_with_profile clears the Chrome profile before the scan.
            credential = await login_with_profile(profile, on_status=on_status)

            def verify() -> tuple[dict[str, Any], dict[str, Any]]:
                health = verify_credential_details(credential, force_refresh=True)
                if not health.get("authenticated"):
                    return health, {}
                with BossClient(credential) as client:
                    return health, dict(client.get_user_info())

            health, info = await run_in_daemon_thread(verify)
            if not health.get("authenticated"):
                raise RuntimeError(str(health.get("reason") or "BOSS 登录校验失败"))
            platform_actor_id = str(info.get("userId") or info.get("uid") or "").strip()
            if not platform_actor_id:
                raise RuntimeError("BOSS 登录成功但没有取得稳定平台 UID")
            _validate_scanned_uid(config, profile, platform_actor_id)
            save_credential(
                credential,
                store=store,
                platform_actor_id=platform_actor_id,
            )
            return {
                "platform_actor_id": platform_actor_id,
                "nickname": str(info.get("name") or info.get("userName") or ""),
            }

        if selected == "douyin":
            from message_adapter.platforms.douyin.browser_login import (
                login_interactive,
                save_browser_login_result,
            )

            on_status("正在清理本机浏览器登录态")
            profile.clear()
            result = await login_interactive(
                profile=profile,
                headless=False,
                on_status=on_status,
            )
            platform_actor_id = str(result.uid or "").strip()
            if not platform_actor_id:
                raise RuntimeError("抖音登录成功但没有取得稳定平台 UID")
            _validate_scanned_uid(config, profile, platform_actor_id)
            save_browser_login_result(
                result,
                store=store,
                browser_profile=str(profile.path),
            )
            return {
                "platform_actor_id": platform_actor_id,
                "nickname": str(result.nickname or ""),
            }

        from message_adapter.platforms.rednote.browser_login import (
            login_interactive,
            save_browser_login_result,
        )

        on_status("正在清理本机浏览器登录态")
        profile.clear()
        result = await login_interactive(
            profile=profile,
            headless=False,
            on_status=on_status,
        )
        platform_actor_id = str(result.user_id or "").strip()
        if not platform_actor_id:
            raise RuntimeError("小红书登录成功但没有取得稳定平台 UID")
        _validate_scanned_uid(config, profile, platform_actor_id)
        save_browser_login_result(
            result,
            store=store,
            browser_profile=str(profile.path),
        )
        return {
            "platform_actor_id": platform_actor_id,
            "nickname": str(result.nickname or ""),
        }
    finally:
        store.close()


async def login_host_platform(
    platform: str,
    config: AdapterConfig,
    on_status: StatusCallback,
) -> dict[str, str]:
    """Accept a WeChat or WeCom account after the host client prints 启动成功."""
    from message_adapter.platforms.host_client import HOST_PLATFORMS, discover_host_account

    selected = str(platform or "").strip().lower()
    if selected not in HOST_PLATFORMS or selected != config.platform:
        raise ValueError("unsupported platform login")
    label = "企业微信" if selected == "wecom" else "微信"
    on_status(f"正在检查本机{label}客户端，不会打开扫码窗口")
    account = await run_in_daemon_thread(discover_host_account, selected)
    if account is None:
        raise RuntimeError(
            f"还没有检测到{label}客户端启动成功。请先打开接入文档，在小主机按文档启动后再登录。"
        )
    platform_actor_id = account["platform_actor_id"]
    _ensure_uid_matches_state(config, platform_actor_id)
    store = CredentialStore(config.credential_db)
    try:
        store.save(
            selected,
            {"source": "qkzd", "nickname": account["nickname"]},
            platform_actor_id=platform_actor_id,
        )
    finally:
        store.close()
    return account


def logout_platform(platform: str, config: AdapterConfig) -> bool:
    """Remove the local credential while preserving UID-bound delivery state.

    BOSS / Douyin / Rednote all clear the managed Chrome profile so the next login
    starts clean. Rednote also drops the legacy ``xiaohongshu`` vault/profile slot.
    Use ``reset`` to archive UID binding / outbox when switching accounts on this machine.
    """
    from message_adapter.platforms.host_client import HOST_PLATFORMS

    selected = str(platform or "").strip().lower()
    if selected not in {*_BROWSER_LOGIN_PLATFORMS, *HOST_PLATFORMS} or selected != config.platform:
        raise ValueError("unsupported platform logout")
    environment_name = {"boss": "BOSS_COOKIES", "douyin": "DY_COOKIE", "rednote": "REDNOTE_COOKIE"}.get(selected, "")
    if environment_name and os.environ.get(environment_name, "").strip():
        raise RuntimeError(f"{selected} 凭证由环境变量提供，网页不能将其退出")
    if selected in _BROWSER_LOGIN_PLATFORMS:
        return purge_browser_credentials(selected, config)
    store = CredentialStore(config.credential_db)
    try:
        return store.delete(selected)
    finally:
        store.close()
