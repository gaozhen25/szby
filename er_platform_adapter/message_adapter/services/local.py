from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import hmac
from importlib import resources
import json
import logging
import random
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
import webbrowser

from message_adapter import __version__
from message_adapter.browser_profiles import BrowserProfile, legacy_profile_issues, migrate_legacy_browser_profile
from message_adapter.config import AdapterConfig
from message_adapter.gateway import ControlGatewayClient, RabbitMQGateway
from message_adapter.gateway.account_alert import (
    AccountAlertClient,
    account_alert_settings,
    alert_transitions,
    online_alert_accounts,
)
from message_adapter.gateway.control import CONTROL_CREDENTIAL_SLOT
from message_adapter.platforms import create_platform_adapter
from message_adapter.platforms.host_client import HOST_PLATFORMS
from message_adapter.process_lock import SingleInstanceLock
from message_adapter.observability import diagnostic_bundle
from message_adapter.storage import CredentialStore, SQLiteStore, migrate_legacy_state_database
from message_adapter.workspaces import (
    Workspace,
    WorkspaceRegistry,
    environment_credential_names,
)

from .accounts import (
    credential_actor_id,
    credential_available,
    login_host_platform,
    login_platform,
    logout_platform,
)
from .docx_view import DOCX_TYPE, HOST_DOC_NAMES, host_doc_bytes, host_doc_media, render_host_doc
from .runtime import AdapterRuntime
from .reset import archive_platform_state

logger = logging.getLogger(__name__)
MESSAGE_PLATFORMS = ("boss", "douyin", "rednote")
CONTROL_PLATFORMS = (*MESSAGE_PLATFORMS, *HOST_PLATFORMS)

APP_DISPLAY_NAME = "轻回桌面连接器"
CONTROL_CREDENTIAL_SLOT = "control_gateway"
WECOM_DOC_NAME = HOST_DOC_NAMES["wecom"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error(exc: BaseException) -> str:
    text = str(exc).strip() or "出现未知错误"
    lowered = text.lower()
    sensitive = (
        "cookie",
        "ticket",
        "private_key",
        "authorization",
        "password",
        "active_code",
        "access_key",
        "sessionid",
    )
    if any(key in lowered for key in sensitive):
        return "出错详情已隐藏"
    text = re.sub(r"(amqps?://)[^:/\s]+:[^@\s]+@", r"\1***:***@", text, flags=re.IGNORECASE)
    text = re.sub(r"([?&](?:token|access_key|sessionid)=)[^&\s]+", r"\1***", text, flags=re.IGNORECASE)
    return text[:500]


@dataclass(slots=True)
class WorkerState:
    state: str = "stopped"
    platform_actor_id: str = ""
    restart_count: int = 0
    last_status_time: str = ""
    last_error: str = ""


@dataclass(slots=True)
class LoginState:
    state: str = "idle"
    message: str = ""
    platform_actor_id: str = ""
    nickname: str = ""
    updated_at: str = ""

    def snapshot(self) -> dict[str, str]:
        return {
            "state": self.state,
            "message": self.message,
            "platform_actor_id": self.platform_actor_id,
            "nickname": self.nickname,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes = b""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    content_type: str
    cache_control: str = "no-store"
    extra_headers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def json(cls, status: int, payload: dict[str, Any]) -> "HttpResponse":
        return cls(
            status=status,
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )


class PlatformWorker:
    RETRY_SECONDS = (2.0, 5.0, 10.0, 30.0, 60.0)

    def __init__(self, platform: str, dotenv: str, data_root: Path | str = Path("adapter_data")):
        self.platform = platform
        self.dotenv = dotenv
        self.data_root = Path(data_root).expanduser().resolve()
        self.status = WorkerState(last_status_time=_now())
        self._runtime: AdapterRuntime | None = None
        self._refresh_event = asyncio.Event()
        self._maintenance = False
        self._owner_lock_held = False

    def _transition(self, state: str, *, error: str = "") -> None:
        if self.status.state != state or error != self.status.last_error:
            self.status.state = state
            self.status.last_error = error
            self.status.last_status_time = _now()

    def snapshot(self) -> dict[str, Any]:
        state = self.status.state
        if state == "ready" and self._runtime is not None and not self._runtime.is_ready:
            state = "retrying"
        return {
            "state": state,
            "platform_actor_id": self.status.platform_actor_id,
            "restart_count": self.status.restart_count,
            "last_status_time": self.status.last_status_time,
            "last_error": self.status.last_error,
        }

    def registration_account(self, login_state: LoginState) -> dict[str, Any] | None:
        snapshot = self.snapshot()
        platform_actor_id = str(snapshot.get("platform_actor_id") or login_state.platform_actor_id)
        if snapshot["state"] != "ready" or not platform_actor_id:
            return None
        actor = self._runtime.actor if self._runtime is not None else None
        return {
            "platform": self.platform,
            "platform_actor_id": platform_actor_id,
            "nickname": actor.username if actor is not None else login_state.nickname,
            "avatar_url": actor.avatar if actor is not None else "",
            "profile": {},
        }

    async def refresh(self) -> None:
        """Wake an offline worker or restart it after credentials change."""
        self._refresh_event.set()
        if self._runtime is not None:
            await self._runtime.stop()

    async def pause_for_maintenance(self, *, timeout: float = 15.0) -> None:
        self._maintenance = True
        await self.refresh()
        deadline = time.monotonic() + timeout
        while not self._owner_lock_held or self._runtime is not None:
            if time.monotonic() >= deadline:
                self._maintenance = False
                self._refresh_event.set()
                raise TimeoutError(
                    f"{self.platform} worker could not acquire its platform lock for maintenance"
                )
            await asyncio.sleep(0.05)

    def resume_after_maintenance(self) -> None:
        self._maintenance = False
        self._refresh_event.set()

    async def _wait_for_refresh_or_stop(
        self,
        stop: asyncio.Event,
        *,
        timeout: float | None = None,
    ) -> str:
        stop_waiter = asyncio.create_task(stop.wait())
        refresh_waiter = asyncio.create_task(self._refresh_event.wait())
        try:
            done, _ = await asyncio.wait(
                (stop_waiter, refresh_waiter),
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_waiter in done:
                return "stop"
            if refresh_waiter in done:
                self._refresh_event.clear()
                return "refresh"
            return "timeout"
        finally:
            stop_waiter.cancel()
            refresh_waiter.cancel()
            await asyncio.gather(stop_waiter, refresh_waiter, return_exceptions=True)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                with SingleInstanceLock(AdapterConfig.owner_lock_for(self.platform, self.data_root)):
                    self._owner_lock_held = True
                    try:
                        await self._supervise(stop)
                    finally:
                        self._owner_lock_held = False
                return
            except asyncio.CancelledError:
                raise
            except RuntimeError as exc:
                error = _safe_error(exc)
                self.status.restart_count += 1
                self._transition("retrying", error=error)
                logger.warning(
                    "platform=%s owner lock unavailable: %s",
                    self.platform,
                    error,
                    exc_info=True,
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
        self._transition("stopped")

    async def _supervise(self, stop: asyncio.Event) -> None:
        attempt = 0
        while not stop.is_set():
            if self._maintenance:
                self._transition("offline")
                if await self._wait_for_refresh_or_stop(stop) == "stop":
                    break
                continue
            config = AdapterConfig.load(
                platform=self.platform,
                dotenv=self.dotenv,
                data_root=self.data_root,
            )
            has_credential = await asyncio.to_thread(credential_available, config)
            if not has_credential:
                self._transition("offline")
                if await self._wait_for_refresh_or_stop(stop) == "stop":
                    break
                attempt = 0
                continue
            self._transition("starting")
            try:
                await self._run_once(stop)
                if stop.is_set():
                    break
                if self._refresh_event.is_set():
                    self._refresh_event.clear()
                    attempt = 0
                    continue
                raise RuntimeError("platform worker stopped unexpectedly")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop.is_set():
                    break
                error = _safe_error(exc)
                self.status.restart_count += 1
                self._transition("retrying", error=error)
                delay = self.RETRY_SECONDS[min(attempt, len(self.RETRY_SECONDS) - 1)]
                attempt += 1
                delay += random.uniform(0, min(1.0, delay * 0.1))
                logger.warning(
                    "platform=%s retrying in %.1fs: %s",
                    self.platform,
                    delay,
                    error,
                    exc_info=True,
                )
                wake_reason = await self._wait_for_refresh_or_stop(stop, timeout=delay)
                if wake_reason == "refresh":
                    attempt = 0
        self._transition("stopped")

    async def _run_once(self, stop: asyncio.Event) -> None:
        config = AdapterConfig.load(
            platform=self.platform,
            dotenv=self.dotenv,
            data_root=self.data_root,
        )
        errors = config.validate(require_gateway=True, require_send_status=True)
        if errors:
            raise ValueError("; ".join(errors))
        profile = BrowserProfile(config.browser_profile_root, self.platform)
        profile_errors = legacy_profile_issues(profile)
        if profile_errors:
            raise RuntimeError("; ".join(profile_errors))
        migrate_legacy_state_database(config)
        migrate_legacy_browser_profile(profile)
        lock_path = config.state_db.with_suffix(config.state_db.suffix + ".lock")
        store: SQLiteStore | None = None
        credentials: CredentialStore | None = None
        runtime_task: asyncio.Task[None] | None = None
        with SingleInstanceLock(lock_path):
            try:
                store = SQLiteStore(config.state_db)
                credentials = CredentialStore(config.credential_db)
                adapter = create_platform_adapter(
                    self.platform,
                    credentials=credentials,
                    browser_profile_root=config.browser_profile_root,
                )
                gateway = None
                if config.control_gateway_url:
                    control_gateway = ControlGatewayClient(config, credentials)
                    gateway = RabbitMQGateway(
                        config,
                        store,
                        before_publish=control_gateway.ensure_audience_from_mq,
                    )
                runtime = AdapterRuntime(config, adapter, store, gateway=gateway)
                self._runtime = runtime
                runtime_task = asyncio.create_task(runtime.run(), name=f"adapter-{self.platform}")
                ready_waiter = asyncio.create_task(runtime.ready_event.wait())
                stop_waiter = asyncio.create_task(stop.wait())
                refresh_waiter = asyncio.create_task(self._refresh_event.wait())
                try:
                    done, _ = await asyncio.wait(
                        (runtime_task, ready_waiter, stop_waiter, refresh_waiter),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if runtime_task in done:
                        await runtime_task
                    if stop_waiter in done:
                        await runtime.stop()
                        await runtime_task
                        return
                    if refresh_waiter in done:
                        await runtime.stop()
                        await runtime_task
                        return
                    actor = runtime.actor
                    self.status.platform_actor_id = actor.platform_actor_id if actor else ""
                    self._transition("ready")
                    while not stop.is_set() and not runtime_task.done():
                        if self._refresh_event.is_set():
                            await runtime.stop()
                            break
                        self._transition("ready" if runtime.is_ready else "retrying")
                        await asyncio.sleep(0.5)
                    if stop.is_set():
                        await runtime.stop()
                    await runtime_task
                finally:
                    ready_waiter.cancel()
                    stop_waiter.cancel()
                    refresh_waiter.cancel()
                    await asyncio.gather(
                        ready_waiter,
                        stop_waiter,
                        refresh_waiter,
                        return_exceptions=True,
                    )
            finally:
                self._runtime = None
                if runtime_task and not runtime_task.done():
                    runtime_task.cancel()
                    await asyncio.gather(runtime_task, return_exceptions=True)
                if store is not None:
                    await asyncio.to_thread(store.close)
                if credentials is not None:
                    await asyncio.to_thread(credentials.close)


class LocalAdapterService:
    MAX_HEADER_BYTES = 32_768
    MAX_BODY_BYTES = 8_192

    def __init__(
        self,
        *,
        dotenv: str,
        health_host: str = "127.0.0.1",
        health_port: int = 8765,
        open_browser: bool = False,
        login_handler: Callable[[str, AdapterConfig, Callable[[str], None]], Awaitable[dict[str, str]]] = login_platform,
        logout_handler: Callable[[str, AdapterConfig], bool] = logout_platform,
        registration_handler: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        data_root: Path | str = Path("adapter_data"),
        manage_logging: bool = False,
        verbose: bool = False,
    ):
        if health_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("health server must listen on a loopback address")
        self.dotenv = dotenv
        self.health_host = health_host
        self.health_port = health_port
        self.open_browser = open_browser
        self.data_root = Path(data_root).expanduser().resolve()
        self.manage_logging = manage_logging
        self.verbose = verbose
        self.started_at = time.monotonic()
        self.stop_event = asyncio.Event()
        self.registry = WorkspaceRegistry(self.data_root)
        self.active_workspace = self._restore_or_migrate_workspace()
        self.workers: dict[str, PlatformWorker] = {}
        self._worker_stop: asyncio.Event | None = None
        self._worker_tasks: dict[str, asyncio.Task[None]] = {}
        self._service_running = False
        self._workspace_lock = asyncio.Lock()
        self._sync_lock = asyncio.Lock()
        self._sync_event = asyncio.Event()
        self._sync_task: asyncio.Task[None] | None = None
        self._alert_task: asyncio.Task[None] | None = None
        self._reported_online: dict[tuple[str, str], float] = {}
        self._alert_config_warned = False
        self.login_states = {
            platform: LoginState(updated_at=_now()) for platform in CONTROL_PLATFORMS
        }
        self._login_tasks: dict[str, asyncio.Task[None]] = {}
        self._login_handler = login_handler
        self._logout_handler = logout_handler
        self._registration_handler = registration_handler
        self._sync_state = self._initial_sync_state()
        self._control_token = secrets.token_urlsafe(32)
        self._server: asyncio.AbstractServer | None = None
        if self.active_workspace is not None:
            self._prepare_workspace(self.active_workspace)
        from message_adapter.platforms.douyin.images import configure_media_base

        configure_media_base(self.url.rstrip("/"))

    def _restore_or_migrate_workspace(self) -> Workspace | None:
        active = self.registry.active()
        if active is not None:
            return active
        if self.registry.has_workspaces() or not self.registry.has_legacy_data():
            return None
        legacy_control = self.registry.legacy_control_state()
        code = legacy_control.get("activation_code", "")
        if not code:
            return None
        workspace = self.registry.create(code, device_id=legacy_control.get("device_id", ""))
        try:
            self.registry.migrate_legacy_into(workspace)
        except Exception:
            logger.exception("legacy adapter data migration failed")
            try:
                self.registry.delete_if_empty(workspace.workspace_id)
            except Exception:
                logger.exception("failed to roll back empty workspace registry entry")
            return None
        return self.registry.set_active(workspace.workspace_id)

    def _prepare_workspace(self, workspace: Workspace) -> None:
        workspace.root.mkdir(parents=True, exist_ok=True)
        try:
            workspace.root.chmod(0o700)
        except OSError:
            pass
        credentials = CredentialStore(workspace.root / "credentials.sqlite3")
        credentials.close()
        self.workers = {
            platform: PlatformWorker(platform, self.dotenv, workspace.root)
            for platform in MESSAGE_PLATFORMS
        }
        from message_adapter.platforms.douyin.images import configure_media_root

        configure_media_root(workspace.root)

    def _config(self, platform: str) -> AdapterConfig:
        if self.active_workspace is None:
            raise RuntimeError("请先登录本地激活码账号")
        return AdapterConfig.load(
            platform=platform,
            dotenv=self.dotenv,
            data_root=self.active_workspace.root,
        )

    def _clear_saved_registration_accounts(self) -> None:
        if self.active_workspace is None:
            return
        credentials = CredentialStore(self.active_workspace.root / "credentials.sqlite3")
        try:
            saved = credentials.get(CONTROL_CREDENTIAL_SLOT) or {}
            if not saved or not saved.get("accounts"):
                return
            credentials.save(CONTROL_CREDENTIAL_SLOT, {**saved, "accounts": []})
        finally:
            credentials.close()

    def _load_control_state(self) -> dict[str, Any]:
        if self.active_workspace is None:
            return {}
        credentials = CredentialStore(
            self.active_workspace.root / "credentials.sqlite3",
            read_only=True,
        )
        try:
            return credentials.get(CONTROL_CREDENTIAL_SLOT) or {}
        finally:
            credentials.close()

    def _initial_sync_state(self) -> dict[str, Any]:
        saved = self._load_control_state()
        accounts = saved.get("accounts") if isinstance(saved.get("accounts"), list) else []
        synced = bool(saved.get("device_token")) and bool(accounts)
        return {
            "state": "synced" if synced else "pending" if self.active_workspace else "idle",
            "message": (
                "已同步到轻回"
                if synced
                else "登录平台后将在后台同步到轻回"
                if self.active_workspace
                else "请先登录本地账号"
            ),
            "configured": self._registration_handler is not None,
            "accounts": accounts,
            "retryable": False,
            "updated_at": _now(),
        }

    def _switch_logging(self, target: Path) -> None:
        if not self.manage_logging:
            return
        from message_adapter.observability import configure_logging

        configure_logging(self.verbose, log_dir=target / "logs")

    @property
    def url(self) -> str:
        host = "[::1]" if self.health_host == "::1" else self.health_host
        return f"http://{host}:{self.health_port}/"

    def live_payload(self) -> dict[str, Any]:
        return {
            "status": "live",
            "name": APP_DISPLAY_NAME,
            "version": __version__,
            "uptime_seconds": round(time.monotonic() - self.started_at, 3),
        }

    def ready_payload(self) -> tuple[int, dict[str, Any]]:
        workers = {
            name: self.workers[name].snapshot()
            if name in self.workers
            else {
                "state": "stopped",
                "platform_actor_id": "",
                "restart_count": 0,
                "last_status_time": "",
                "last_error": "",
            }
            for name in MESSAGE_PLATFORMS
        }
        ready_count = sum(item["state"] == "ready" for item in workers.values())
        if ready_count == len(MESSAGE_PLATFORMS):
            status = "ready"
        elif ready_count:
            status = "partial"
        else:
            status = "unavailable"
        return (200 if ready_count else 503), {"status": status, "platforms": workers}

    async def control_payload(self) -> dict[str, Any]:
        platforms: dict[str, Any] = {}
        for platform in CONTROL_PLATFORMS:
            login_state = self.login_states[platform].snapshot()
            if self.active_workspace is None:
                platforms[platform] = {
                    "state": "stopped",
                    "platform_actor_id": "",
                    "restart_count": 0,
                    "last_status_time": "",
                    "last_error": "",
                    "online": False,
                    "credential_present": False,
                    "registered": False,
                    "login": login_state,
                }
                continue
            config = self._config(platform)
            credential_present, credential_uid = await asyncio.gather(
                asyncio.to_thread(credential_available, config),
                asyncio.to_thread(credential_actor_id, config),
            )
            if platform in self.workers:
                worker_state = self.workers[platform].snapshot()
                platform_actor_id = str(
                    worker_state.get("platform_actor_id")
                    or login_state.get("platform_actor_id")
                    or credential_uid
                    or ""
                )
            else:
                platform_actor_id = str(login_state.get("platform_actor_id") or credential_uid or "")
                worker_state = {
                    "state": "ready" if credential_present and platform_actor_id else "offline",
                    "platform_actor_id": platform_actor_id,
                    "restart_count": 0,
                    "last_status_time": login_state.get("updated_at") or "",
                    "last_error": login_state.get("message") if login_state.get("state") == "error" else "",
                }
            registered = any(
                isinstance(item, dict)
                and str(item.get("platform") or "") == platform
                and str(item.get("platform_actor_id") or "") == platform_actor_id
                for item in self._sync_state.get("accounts", [])
            )
            login_blocked = str(login_state.get("state") or "") in {"starting", "waiting", "error"}
            worker_failed = worker_state["state"] in {"retrying", "error"}
            sync_failed = self._sync_state.get("state") == "error"
            # 在线表示收发可用：消息连接就绪，且这次同步没有失败。
            if platform in self.workers:
                online = bool(
                    credential_present
                    and platform_actor_id
                    and registered
                    and worker_state["state"] == "ready"
                    and not login_blocked
                    and not worker_failed
                    and not sync_failed
                )
            else:
                online = bool(
                    credential_present
                    and platform_actor_id
                    and registered
                    and not login_blocked
                    and not sync_failed
                )
            platforms[platform] = {
                **worker_state,
                "online": online,
                "credential_present": credential_present,
                "platform_actor_id": platform_actor_id,
                "registered": registered,
                "login": login_state,
            }
        return {
            "service": self.live_payload(),
            "platforms": platforms,
            "local_account": {
                "logged_in": self.active_workspace is not None,
                "workspace_id": self.active_workspace.workspace_id if self.active_workspace else "",
                "activation_code": self.active_workspace.activation_code if self.active_workspace else "",
                "created_at": self.active_workspace.created_at if self.active_workspace else "",
            },
            "upstream_sync": dict(self._sync_state),
        }

    async def _start_workers(self) -> None:
        if not self._service_running or self.active_workspace is None or self._worker_tasks:
            return
        self._worker_stop = asyncio.Event()
        self._worker_tasks = {
            platform: asyncio.create_task(
                worker.run(self._worker_stop),
                name=f"worker-{platform}-{self.active_workspace.workspace_id[:8]}",
            )
            for platform, worker in self.workers.items()
        }

    async def _stop_workers(self) -> None:
        for task in self._login_tasks.values():
            if not task.done():
                task.cancel()
        if self._login_tasks:
            await asyncio.gather(*self._login_tasks.values(), return_exceptions=True)
        self._login_tasks.clear()
        if self._worker_stop is not None:
            self._worker_stop.set()
        tasks = list(self._worker_tasks.values())
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=5.0)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self._worker_tasks.clear()
        self._worker_stop = None

    def _reset_login_states(self) -> None:
        self.login_states = {
            platform: LoginState(updated_at=_now()) for platform in CONTROL_PLATFORMS
        }

    async def login_local_account(self, activation_code: str, *, create: bool = False) -> tuple[Workspace, bool]:
        code = str(activation_code or "").strip()
        if not 4 <= len(code) <= 256:
            raise ValueError("请输入有效的激活码")
        injected = environment_credential_names()
        if injected:
            raise RuntimeError("环境变量平台凭证无法隔离到工作区，请先移除: " + ", ".join(injected))
        async with self._workspace_lock:
            found = await asyncio.to_thread(self.registry.find, code)
            created = False
            claim_legacy = bool(
                found is None
                and create
                and not self.registry.has_workspaces()
                and self.registry.has_legacy_data()
            )
            if found is None:
                if not create:
                    raise LookupError("本机没有这个激活码对应的工作区")
                found = await asyncio.to_thread(self.registry.create, code)
                created = True
            if self.active_workspace and self.active_workspace.workspace_id == found.workspace_id:
                return self.active_workspace, created
            async with self._sync_lock:
                previous = self.active_workspace
                await self._stop_workers()
                if self.active_workspace is not None:
                    self._switch_logging(self.data_root)
                if claim_legacy:
                    try:
                        await asyncio.to_thread(self.registry.migrate_legacy_into, found)
                    except Exception:
                        await asyncio.to_thread(self.registry.delete_if_empty, found.workspace_id)
                        if previous is not None:
                            self.active_workspace = previous
                            self._prepare_workspace(previous)
                            self._switch_logging(previous.root)
                            await self._start_workers()
                        raise
                self.active_workspace = await asyncio.to_thread(
                    self.registry.set_active,
                    found.workspace_id,
                )
                self._prepare_workspace(self.active_workspace)
                self._reset_login_states()
                self._sync_state = self._initial_sync_state()
                self._switch_logging(self.active_workspace.root)
                await self._start_workers()
                self._sync_event.set()
                logger.info(
                    "local workspace mounted workspace_id=%s created=%s",
                    self.active_workspace.workspace_id,
                    created,
                )
                return self.active_workspace, created

    async def logout_local_account(self) -> None:
        async with self._workspace_lock:
            async with self._sync_lock:
                if self.active_workspace is None:
                    return
                workspace_id = self.active_workspace.workspace_id
                await self._stop_workers()
                self._switch_logging(self.data_root)
                await asyncio.to_thread(self.registry.clear_active)
                self.active_workspace = None
                self.workers = {}
                self._reset_login_states()
                self._sync_state = self._initial_sync_state()
                logger.info("local workspace unmounted workspace_id=%s", workspace_id)

    async def reset_local_account(self, confirmation: str) -> str:
        if confirmation != "重置当前工作区":
            raise ValueError("确认文字不正确")
        injected = environment_credential_names()
        if injected:
            raise RuntimeError("环境变量平台凭证无法隔离到工作区，请先移除: " + ", ".join(injected))
        async with self._workspace_lock:
            async with self._sync_lock:
                workspace = self.active_workspace
                if workspace is None:
                    raise RuntimeError("请先登录本地激活码账号")
                await self._stop_workers()
                self._switch_logging(self.data_root)
                try:
                    archive = await asyncio.to_thread(
                        self.registry.archive_and_recreate,
                        workspace,
                    )
                except Exception:
                    self._switch_logging(workspace.root)
                    await self._start_workers()
                    raise
                self.active_workspace = self.registry.get(workspace.workspace_id)
                assert self.active_workspace is not None
                self._prepare_workspace(self.active_workspace)
                self._reset_login_states()
                self._sync_state = self._initial_sync_state()
                self._switch_logging(self.active_workspace.root)
                await self._start_workers()
                logger.info(
                    "local workspace reset workspace_id=%s archive=%s",
                    workspace.workspace_id,
                    archive,
                )
                return str(archive)

    async def start_login(self, platform: str) -> bool:
        if self.active_workspace is None:
            raise RuntimeError("请先登录本地激活码账号")
        selected = str(platform or "").strip().lower()
        if selected not in self.login_states:
            raise ValueError("unsupported platform")
        current = self._login_tasks.get(selected)
        if current is not None and not current.done():
            return False
        state = self.login_states[selected]
        state.state = "starting"
        state.message = "正在检查本机客户端" if selected in HOST_PLATFORMS else "正在准备扫码窗口"
        state.platform_actor_id = ""
        state.nickname = ""
        state.updated_at = _now()
        self._login_tasks[selected] = asyncio.create_task(
            self._run_login(selected),
            name=f"web-login-{selected}",
        )
        return True

    async def _run_login(self, platform: str) -> None:
        state = self.login_states[platform]
        config = self._config(platform)

        def status(message: str) -> None:
            state.state = "waiting"
            state.message = str(message or "正在等待扫码")[:200]
            state.updated_at = _now()

        try:
            worker = self.workers.get(platform)
            if platform not in HOST_PLATFORMS:
                if worker is not None and platform in self._worker_tasks:
                    status("正在停止当前消息服务")
                    await worker.pause_for_maintenance()
            if platform in HOST_PLATFORMS:
                result = await login_host_platform(platform, config, status)
            else:
                result = await self._login_handler(platform, config, status)
        except asyncio.CancelledError:
            state.state = "idle"
            state.message = "登录已取消"
            state.updated_at = _now()
            raise
        except Exception as exc:
            logger.exception("platform login failed platform=%s", platform)
            state.state = "error"
            state.message = _safe_error(exc)
            state.updated_at = _now()
        else:
            state.state = "success"
            state.message = "登录成功" if platform in HOST_PLATFORMS else "登录成功，正在连接消息服务"
            state.platform_actor_id = str(result.get("platform_actor_id") or "")
            state.nickname = str(result.get("nickname") or "")
            state.updated_at = _now()
        finally:
            worker = self.workers.get(platform)
            if worker is not None and platform in self._worker_tasks:
                worker.resume_after_maintenance()
        if state.state == "success":
            self._sync_event.set()

    async def logout(self, platform: str) -> bool:
        selected = str(platform or "").strip().lower()
        if selected not in self.login_states:
            raise ValueError("unsupported platform")
        task = self._login_tasks.get(selected)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        config = self._config(selected)
        worker = self.workers.get(selected)
        worker_running = worker is not None and selected in self._worker_tasks
        if worker_running:
            assert worker is not None
            await worker.pause_for_maintenance()
        try:
            removed = await asyncio.to_thread(self._logout_handler, selected, config)
        finally:
            if worker_running:
                assert worker is not None
                worker.resume_after_maintenance()
        state = self.login_states[selected]
        state.state = "idle"
        state.message = "已退出登录"
        state.platform_actor_id = ""
        state.nickname = ""
        state.updated_at = _now()
        self._sync_event.set()
        return removed

    async def reset_platform(self, platform: str, confirm_uid: str) -> str:
        selected = str(platform or "").strip().lower()
        if selected not in MESSAGE_PLATFORMS:
            raise ValueError("unsupported platform reset")
        uid = str(confirm_uid or "").strip()
        if not uid:
            raise ValueError("confirm_uid is required")
        task = self._login_tasks.get(selected)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        worker = self.workers[selected]
        worker_running = selected in self._worker_tasks
        if worker_running:
            await worker.pause_for_maintenance()
        try:
            config = self._config(selected)
            archive = await asyncio.to_thread(
                archive_platform_state,
                config,
                uid,
                acquire_owner_lock=not worker_running,
            )
            state = self.login_states[selected]
            state.state = "idle"
            state.message = "旧账号已安全归档，可以扫码登录新账号"
            state.platform_actor_id = ""
            state.nickname = ""
            state.updated_at = _now()
            worker.status.platform_actor_id = ""
            logger.info("platform state archived platform=%s archive=%s", selected, archive)
            self._sync_event.set()
            return str(archive)
        finally:
            if worker_running:
                worker.resume_after_maintenance()

    def _registration_account(self, platform: str) -> dict[str, Any] | None:
        config = self._config(platform)
        if not credential_available(config):
            return None
        platform_actor_id = credential_actor_id(config)
        if not platform_actor_id:
            return None
        credentials = CredentialStore(config.credential_db, read_only=True)
        try:
            saved = credentials.get(platform) or {}
        finally:
            credentials.close()
        nickname = self.login_states[platform].nickname or str(saved.get("nickname") or "")
        return {
            "platform": platform,
            "platform_actor_id": platform_actor_id,
            "nickname": nickname,
            "avatar_url": "",
            "profile": {},
        }

    def _registration_accounts(self) -> list[dict[str, Any]]:
        if self.active_workspace is None:
            return []
        return [
            account
            for platform in CONTROL_PLATFORMS
            if (account := self._registration_account(platform)) is not None
        ]

    async def _call_registration_handler(
        self,
        accounts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        assert self.active_workspace is not None
        assert self._registration_handler is not None
        import inspect

        parameter_count = len(inspect.signature(self._registration_handler).parameters)
        args: list[Any] = [self.active_workspace.activation_code, accounts]
        if parameter_count >= 3:
            args.append(self.active_workspace.device_id)
        if parameter_count >= 4:
            args.append(str(self.active_workspace.root))
        return await self._registration_handler(*args)

    async def sync_upstream(self) -> HttpResponse:
        async with self._sync_lock:
            if self.active_workspace is None:
                return HttpResponse.json(409, {"ok": False, "error": "请先登录本地激活码账号"})
            accounts = await asyncio.to_thread(self._registration_accounts)
            if not accounts:
                self._sync_state.update(
                    state="pending",
                    message="请先登录至少一个平台",
                    accounts=[],
                    retryable=False,
                    updated_at=_now(),
                )
                return HttpResponse.json(202, {"ok": True, "state": "pending"})
            if self._registration_handler is None:
                self._sync_state.update(
                    state="pending",
                    message="轻回 Gateway 尚未配置，本地消息将继续保存",
                    retryable=False,
                    updated_at=_now(),
                )
                return HttpResponse.json(202, {"ok": True, "state": "pending"})
            self._sync_state.update(
                state="syncing",
                message="正在同步到轻回",
                updated_at=_now(),
            )
            try:
                result = await self._call_registration_handler(accounts)
            except Exception as exc:
                logger.exception("control gateway background sync failed account_count=%s", len(accounts))
                retryable = bool(getattr(exc, "retryable", True))
                update: dict[str, Any] = {
                    "state": "error",
                    "message": _safe_error(exc),
                    "retryable": retryable,
                    "updated_at": _now(),
                }
                if not retryable:
                    # IM 拒绝后，不能继续沿用上一次成功的账号登记。
                    update["accounts"] = []
                    await asyncio.to_thread(self._clear_saved_registration_accounts)
                self._sync_state.update(**update)
                return HttpResponse.json(502, {"ok": False, "error": self._sync_state["message"]})
            registrations = result.get("accounts") if isinstance(result.get("accounts"), list) else []
            if not registrations:
                registrations = [
                    {
                        "platform": item["platform"],
                        "platform_actor_id": item["platform_actor_id"],
                    }
                    for item in accounts
                ]
            self._sync_state.update(
                state="synced",
                message="已同步到轻回",
                accounts=registrations,
                retryable=False,
                updated_at=_now(),
            )
            return HttpResponse.json(200, {"ok": True, "state": "synced"})

    async def _sync_loop(self) -> None:
        retry_seconds = (2.0, 5.0, 10.0, 30.0, 60.0)
        while not self.stop_event.is_set():
            event_waiter = asyncio.create_task(self._sync_event.wait())
            stop_waiter = asyncio.create_task(self.stop_event.wait())
            done, _ = await asyncio.wait(
                (event_waiter, stop_waiter),
                return_when=asyncio.FIRST_COMPLETED,
            )
            event_waiter.cancel()
            stop_waiter.cancel()
            await asyncio.gather(event_waiter, stop_waiter, return_exceptions=True)
            if self.stop_event.is_set():
                return
            self._sync_event.clear()
            attempt = 0
            while self.active_workspace is not None and not self.stop_event.is_set():
                response = await self.sync_upstream()
                if response.status < 500 or not self._sync_state.get("retryable", False):
                    break
                delay = retry_seconds[min(attempt, len(retry_seconds) - 1)]
                attempt += 1
                wake = asyncio.create_task(self._sync_event.wait())
                stopped = asyncio.create_task(self.stop_event.wait())
                done, _ = await asyncio.wait(
                    (wake, stopped),
                    timeout=delay,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                wake.cancel()
                stopped.cancel()
                await asyncio.gather(wake, stopped, return_exceptions=True)
                if self.stop_event.is_set():
                    return
                if done:
                    self._sync_event.clear()
                    attempt = 0

    def _account_alert_client(self) -> AccountAlertClient | None:
        url, secret = account_alert_settings(self.dotenv)
        if not url or not secret:
            if not self._alert_config_warned:
                logger.warning("ACCOUNT_ALERT_URL or ACCOUNT_ALERT_INTERNAL_SECRET is not configured")
                self._alert_config_warned = True
            return None
        return AccountAlertClient(url, secret)

    async def _send_account_alert(self, platform: str, platform_id: str, alert_type: str) -> bool:
        client = self._account_alert_client()
        if client is None:
            return False
        await client.send(platform, platform_id, alert_type)
        logger.info(
            "account alert sent platform=%s platform_id=%s alert_type=%s",
            platform,
            platform_id,
            alert_type,
        )
        return True

    async def _account_alert_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload = await self.control_payload()
                current = tuple(
                    (item["platform"], item["platform_id"])
                    for item in online_alert_accounts(payload.get("platforms") or {})
                )
                actions = alert_transitions(self._reported_online, current, now=time.monotonic())
                for platform, platform_id, alert_type in actions:
                    try:
                        sent = await self._send_account_alert(platform, platform_id, alert_type)
                    except Exception as exc:
                        logger.warning(
                            "account alert failed platform=%s alert_type=%s error=%s",
                            platform,
                            alert_type,
                            _safe_error(exc),
                        )
                        continue
                    if not sent:
                        continue
                    if alert_type == "online":
                        self._reported_online[(platform, platform_id)] = time.monotonic()
                    else:
                        self._reported_online.pop((platform, platform_id), None)
            except Exception:
                logger.exception("account alert heartbeat failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=2)
            except TimeoutError:
                continue

    async def _send_offline_alerts(self) -> None:
        for platform, platform_id in list(self._reported_online):
            try:
                sent = await self._send_account_alert(platform, platform_id, "offline")
            except Exception as exc:
                logger.warning(
                    "account offline alert failed platform=%s error=%s",
                    platform,
                    _safe_error(exc),
                )
                continue
            if sent:
                self._reported_online.pop((platform, platform_id), None)

    @staticmethod
    def _asset(name: str) -> bytes:
        return resources.files("message_adapter.web").joinpath(name).read_bytes()

    def _authorized(self, request: HttpRequest) -> bool:
        supplied = request.headers.get("x-adapter-control", "")
        return bool(supplied) and hmac.compare_digest(supplied, self._control_token)

    async def dispatch(self, request: HttpRequest) -> HttpResponse:
        path = urlsplit(request.path).path
        if request.method == "GET":
            if path == "/":
                return HttpResponse(200, self._asset("index.html"), "text/html; charset=utf-8", "no-cache")
            if path == "/app.css":
                return HttpResponse(200, self._asset("app.css"), "text/css; charset=utf-8", "no-cache")
            if path == "/app.js":
                return HttpResponse(200, self._asset("app.js"), "text/javascript; charset=utf-8", "no-cache")
            logo = re.fullmatch(r"/logos/(boss|douyin|wechat|wecom|rednote)\.(png|svg)", path)
            if logo:
                return self._logo(f"{logo.group(1)}.{logo.group(2)}")
            host_doc = re.fullmatch(r"/docs/(wechat|wecom)", path)
            if host_doc:
                page = render_host_doc(host_doc.group(1)).encode("utf-8")
                return HttpResponse(200, page, "text/html; charset=utf-8", "no-cache")
            host_media = re.fullmatch(r"/docs/(wechat|wecom)/media/(image[0-9]+\.png)", path)
            if host_media:
                return self._host_doc_media(host_media.group(1), host_media.group(2))
            host_file = re.fullmatch(r"/docs/(wechat|wecom)\.docx", path)
            if host_file:
                return self._host_doc_file(host_file.group(1))
            if path == "/api/session":
                return HttpResponse.json(200, {"control_token": self._control_token})
            if path == "/api/state":
                return HttpResponse.json(200, await self.control_payload())
            if path == "/health/live":
                return HttpResponse.json(200, self.live_payload())
            if path == "/health/ready":
                status, payload = self.ready_payload()
                return HttpResponse.json(status, payload)
            media = re.fullmatch(r"/media/douyin/([0-9a-f]{32}\.(?:jpg|png|webp|gif))", path)
            if media:
                return self._douyin_media(media.group(1))
            return HttpResponse.json(404, {"ok": False, "error": "not_found"})

        if request.method != "POST":
            return HttpResponse.json(405, {"ok": False, "error": "method_not_allowed"})
        if not self._authorized(request):
            return HttpResponse.json(403, {"ok": False, "error": "forbidden"})
        try:
            payload = json.loads(request.body.decode("utf-8")) if request.body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return HttpResponse.json(400, {"ok": False, "error": "invalid_json"})
        if not isinstance(payload, dict):
            return HttpResponse.json(400, {"ok": False, "error": "invalid_json"})

        if path == "/api/local-account/login":
            try:
                workspace, created = await self.login_local_account(
                    str(payload.get("activation_code") or ""),
                    create=bool(payload.get("create", False)),
                )
                return HttpResponse.json(
                    200,
                    {
                        "ok": True,
                        "created": created,
                        "workspace_id": workspace.workspace_id,
                    },
                )
            except LookupError as exc:
                return HttpResponse.json(
                    409,
                    {
                        "ok": False,
                        "error": str(exc),
                        "code": "workspace_not_found",
                        "can_create": True,
                    },
                )
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                logger.exception("local workspace login failed")
                return HttpResponse.json(409, {"ok": False, "error": _safe_error(exc)})
        if path == "/api/local-account/logout":
            try:
                await self.logout_local_account()
                return HttpResponse.json(200, {"ok": True})
            except Exception as exc:
                logger.exception("local workspace logout failed")
                return HttpResponse.json(409, {"ok": False, "error": _safe_error(exc)})
        if path == "/api/local-account/reset":
            try:
                archive = await self.reset_local_account(str(payload.get("confirmation") or ""))
                return HttpResponse.json(200, {"ok": True, "archive": archive})
            except Exception as exc:
                logger.exception("local workspace reset failed")
                return HttpResponse.json(409, {"ok": False, "error": _safe_error(exc)})
        if path == "/api/local-account/sync":
            return await self.sync_upstream()

        match = re.fullmatch(r"/api/platforms/(boss|douyin|rednote|wechat|wecom)/(login|logout)", path)
        if match:
            platform, action = match.groups()
            try:
                if action == "login":
                    if not await self.start_login(platform):
                        return HttpResponse.json(409, {"ok": False, "error": "登录正在进行中"})
                    return HttpResponse.json(202, {"ok": True})
                removed = await self.logout(platform)
                return HttpResponse.json(200, {"ok": True, "removed": removed})
            except Exception as exc:
                return HttpResponse.json(409, {"ok": False, "error": _safe_error(exc)})
        reset_match = re.fullmatch(r"/api/platforms/(boss|douyin|rednote)/reset", path)
        if reset_match:
            platform = reset_match.group(1)
            try:
                archive = await self.reset_platform(
                    platform,
                    str(payload.get("confirm_uid") or ""),
                )
                return HttpResponse.json(200, {"ok": True, "archive": archive})
            except Exception as exc:
                logger.exception("platform reset failed platform=%s", platform)
                return HttpResponse.json(409, {"ok": False, "error": _safe_error(exc)})
        if path == "/api/diagnostics/download":
            try:
                snapshot = await self.control_payload()
                body = await asyncio.to_thread(
                    diagnostic_bundle,
                    state=snapshot,
                    dotenv=self.dotenv,
                    log_dir=(
                        self.active_workspace.root / "logs"
                        if self.active_workspace is not None
                        else self.data_root / "logs"
                    ),
                )
                filename = f"adapter-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
                return HttpResponse(
                    200,
                    body,
                    "application/zip",
                    "no-store",
                    extra_headers=(("Content-Disposition", f'attachment; filename="{filename}"'),),
                )
            except Exception:
                logger.exception("diagnostic bundle creation failed")
                return HttpResponse.json(500, {"ok": False, "error": "诊断包生成失败，请查看本机日志"})
        if path == "/api/shutdown":
            asyncio.get_running_loop().call_later(0.1, self.stop_event.set)
            return HttpResponse.json(200, {"ok": True})
        return HttpResponse.json(404, {"ok": False, "error": "not_found"})

    def _logo(self, name: str) -> HttpResponse:
        content_type = "image/svg+xml" if name.endswith(".svg") else "image/png"
        body = resources.files("message_adapter.web").joinpath("logos", name).read_bytes()
        return HttpResponse(200, body, content_type, "public, max-age=86400")

    def _host_doc_file(self, platform: str) -> HttpResponse:
        filename = quote(HOST_DOC_NAMES[platform])
        return HttpResponse(
            200,
            host_doc_bytes(platform),
            DOCX_TYPE,
            "no-cache",
            extra_headers=(("Content-Disposition", f"inline; filename*=UTF-8''{filename}"),),
        )

    @staticmethod
    def _host_doc_media(platform: str, name: str) -> HttpResponse:
        body = host_doc_media(platform, name)
        if body is None:
            return HttpResponse.json(404, {"ok": False, "error": "not_found"})
        return HttpResponse(200, body, "image/png", "no-cache")

    @staticmethod
    def _douyin_media(name: str) -> HttpResponse:
        from message_adapter.platforms.douyin.images import load_media

        loaded = load_media(name)
        if loaded is None:
            return HttpResponse.json(404, {"ok": False, "error": "not_found"})
        body, content_type = loaded
        return HttpResponse(
            200,
            body,
            content_type,
            "public, max-age=86400",
            extra_headers=(
                ("Access-Control-Allow-Origin", "*"),
                ("Content-Disposition", f'inline; filename="{name}"'),
            ),
        )

    async def _read_request(self, reader: asyncio.StreamReader) -> HttpRequest:
        raw_headers = await reader.readuntil(b"\r\n\r\n")
        if len(raw_headers) > self.MAX_HEADER_BYTES:
            raise ValueError("headers_too_large")
        lines = raw_headers[:-4].decode("iso-8859-1").split("\r\n")
        request_line = lines[0].split()
        if len(request_line) != 3:
            raise ValueError("invalid_request_line")
        method, path, _ = request_line
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                raise ValueError("invalid_header")
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError as exc:
            raise ValueError("invalid_content_length") from exc
        if content_length < 0 or content_length > self.MAX_BODY_BYTES:
            raise ValueError("body_too_large")
        body = await reader.readexactly(content_length) if content_length else b""
        return HttpRequest(method=method.upper(), path=path, headers=headers, body=body)

    async def _write_response(self, writer: asyncio.StreamWriter, response: HttpResponse) -> None:
        reasons = {
            200: "OK",
            202: "Accepted",
            400: "Bad Request",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            409: "Conflict",
            413: "Content Too Large",
            500: "Internal Server Error",
            501: "Not Implemented",
            502: "Bad Gateway",
            503: "Service Unavailable",
        }
        head = (
            f"HTTP/1.1 {response.status} {reasons.get(response.status, 'Error')}\r\n"
            f"Content-Type: {response.content_type}\r\n"
            f"Content-Length: {len(response.body)}\r\n"
            f"Cache-Control: {response.cache_control}\r\n"
            + "".join(f"{name}: {value}\r\n" for name, value in response.extra_headers)
            + "X-Content-Type-Options: nosniff\r\n"
            "Referrer-Policy: no-referrer\r\n"
            "Content-Security-Policy: default-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(head + response.body)
        await writer.drain()

    async def _handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(self._read_request(reader), timeout=5)
            response = await self.dispatch(request)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
            response = HttpResponse.json(400, {"ok": False, "error": "bad_request"})
        except Exception:
            logger.exception("local control request failed")
            response = HttpResponse.json(500, {"ok": False, "error": "internal_error"})
        try:
            await self._write_response(writer, response)
        finally:
            writer.close()
            await writer.wait_closed()

    async def run(self, *, workspace_lock_held: bool = False) -> None:
        workspace_lock = None
        if not workspace_lock_held:
            workspace_lock = SingleInstanceLock(
                self.data_root / ".locks" / "workspace-manager.lock"
            )
            workspace_lock.__enter__()
        try:
            self._server = await asyncio.start_server(
                self._handle_http,
                self.health_host,
                self.health_port,
            )
            self._service_running = True
            if self.active_workspace is not None:
                self._switch_logging(self.active_workspace.root)
            await self._start_workers()
            self._sync_task = asyncio.create_task(
                self._sync_loop(),
                name="workspace-upstream-sync",
            )
            self._alert_task = asyncio.create_task(
                self._account_alert_loop(),
                name="account-alert",
            )
            if self.active_workspace is not None:
                self._sync_event.set()
            logger.info("local control page ready url=%s", self.url)
            if self.open_browser:
                await asyncio.to_thread(webbrowser.open, self.url)
            await self.stop_event.wait()
        finally:
            self.stop_event.set()
            if self._alert_task is not None:
                self._alert_task.cancel()
                await asyncio.gather(self._alert_task, return_exceptions=True)
                self._alert_task = None
            try:
                await asyncio.wait_for(self._send_offline_alerts(), timeout=5)
            except Exception:
                logger.warning("account offline alert failed")
            await self._stop_workers()
            if self._sync_task is not None:
                self._sync_task.cancel()
                await asyncio.gather(self._sync_task, return_exceptions=True)
                self._sync_task = None
            self._service_running = False
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
            await asyncio.to_thread(self.registry.close)
            if workspace_lock is not None:
                workspace_lock.__exit__(None, None, None)
