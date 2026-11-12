from __future__ import annotations

import asyncio
import json
import signal
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from message_adapter import __version__
from message_adapter.browser_profiles import BrowserProfile, legacy_profile_issues, migrate_legacy_browser_profile
from message_adapter.config import AdapterConfig
from message_adapter.gateway import probe_rabbitmq, registration_handler_from_dotenv, watch_rabbitmq
from message_adapter.platforms import create_platform_adapter
from message_adapter.platforms.boss.cli import boss
from message_adapter.platforms.douyin.cli import douyin
from message_adapter.process_lock import SingleInstanceLock
from message_adapter.restart_guard import arm_restart_guard
from message_adapter.observability import (
    ActivityFormatter,
    JsonFormatter,
    activity_color_enabled as _activity_color_enabled,
    configure_logging as _configure_logging,
    install_asyncio_exception_logging,
)
from message_adapter.services import AdapterRuntime, LocalAdapterService
from message_adapter.services.reset import archive_platform_state
from message_adapter.storage import (
    CredentialStore,
    SQLiteStore,
    inspect_actor_binding,
    inspect_database,
    inspect_state_slot_count,
    inspect_unowned_outbox_count,
    legacy_state_issues,
    migrate_legacy_state_database,
)
from message_adapter.workspaces import active_workspace_root

__all__ = ["ActivityFormatter", "JsonFormatter", "_activity_color_enabled", "cli"]


def _config(platform: str, dotenv: str, *, require_workspace: bool = False) -> AdapterConfig:
    root = active_workspace_root()
    if require_workspace and root is None:
        raise click.ClickException("请先启动 adapter serve 并在网页中登录本地激活码账号")
    return AdapterConfig.load(platform=platform, dotenv=dotenv, data_root=root)


def _workspace_manager_lock() -> SingleInstanceLock:
    root = active_workspace_root()
    if root is None:
        raise click.ClickException("请先启动 adapter serve 并在网页中登录本地激活码账号")
    return SingleInstanceLock(root.parent.parent / ".locks" / "workspace-manager.lock")


def _echo_errors(errors: list[str]) -> None:
    for error in errors:
        click.echo(f"- {error}", err=True)


@click.group()
@click.version_option(version=__version__, prog_name="adapter")
def cli() -> None:
    """多平台消息 Adapter 的运行、登录与诊断工具。"""


@cli.command("run")
@click.option("--platform", type=click.Choice(["boss", "douyin", "rednote"]), required=True)
@click.option("--dotenv", default=".env", show_default=True, type=click.Path(dir_okay=False))
@click.option("-v", "--verbose", is_flag=True)
def run_command(platform: str, dotenv: str, verbose: bool) -> None:
    """Run one platform slot until interrupted."""
    _configure_logging(verbose)
    config = _config(platform, dotenv, require_workspace=True)
    errors = config.validate(require_gateway=True, require_send_status=True)
    if errors:
        _echo_errors(errors)
        raise click.ClickException("adapter configuration is incomplete")
    try:
        with _workspace_manager_lock(), SingleInstanceLock(config.owner_lock_path):
            profile = BrowserProfile(config.browser_profile_root, platform)
            profile_errors = legacy_profile_issues(profile)
            if profile_errors:
                raise click.ClickException("; ".join(profile_errors))
            migrate_legacy_state_database(config)
            migrate_legacy_browser_profile(profile)
            store = SQLiteStore(config.state_db)
            credentials = CredentialStore(config.credential_db)
            adapter = create_platform_adapter(
                config.platform,
                credentials=credentials,
                browser_profile_root=config.browser_profile_root,
            )
            runtime = AdapterRuntime(config, adapter, store)

            async def run() -> None:
                loop = asyncio.get_running_loop()
                install_asyncio_exception_logging(loop)
                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(sig, runtime.stop_event.set)
                    except NotImplementedError:
                        pass
                await runtime.run()

            lock_path = config.state_db.with_suffix(config.state_db.suffix + ".lock")
            try:
                with SingleInstanceLock(lock_path):
                    asyncio.run(run())
            finally:
                store.close()
                credentials.close()
    except KeyboardInterrupt:
        pass


@cli.command("serve")
@click.option("--health-host", default="127.0.0.1", show_default=True)
@click.option("--health-port", default=8765, show_default=True, type=click.IntRange(1, 65535))
@click.option("--dotenv", default=".env", show_default=True, type=click.Path(dir_okay=False))
@click.option("--open-browser/--no-open-browser", default=True, show_default=True)
@click.option("-v", "--verbose", is_flag=True)
def serve_command(
    health_host: str,
    health_port: int,
    dotenv: str,
    open_browser: bool,
    verbose: bool,
) -> None:
    """Run the local control page and its platform workers."""
    _configure_logging(verbose)
    arm_restart_guard()

    async def run() -> None:
        install_asyncio_exception_logging(asyncio.get_running_loop())
        with SingleInstanceLock(Path("adapter_data/.locks/workspace-manager.lock")):
            service = LocalAdapterService(
                dotenv=dotenv,
                health_host=health_host,
                health_port=health_port,
                open_browser=open_browser,
                registration_handler=registration_handler_from_dotenv(dotenv),
                manage_logging=True,
                verbose=verbose,
            )
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, service.stop_event.set)
                except NotImplementedError:
                    pass
            await service.run(workspace_lock_held=True)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


@cli.command("reset")
@click.option("--platform", type=click.Choice(["boss", "douyin", "rednote"]), required=True)
@click.option("--confirm-uid", required=True, help="The currently bound platform UID.")
@click.option("--dotenv", default=".env", show_default=True, type=click.Path(dir_okay=False))
def reset_command(platform: str, confirm_uid: str, dotenv: str) -> None:
    """Archive and detach one platform slot after exact UID confirmation."""
    config = _config(platform, dotenv, require_workspace=True)
    try:
        with _workspace_manager_lock():
            archive = archive_platform_state(config, confirm_uid)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"ok": True, "platform": platform, "archive": str(archive)}, ensure_ascii=False, indent=2))


@cli.command("doctor")
@click.option("--platform", type=click.Choice(["boss", "douyin", "rednote"]), required=True)
@click.option("--dotenv", default=".env", show_default=True, type=click.Path(dir_okay=False))
@click.option("--skip-platform", is_flag=True, help="Only validate local configuration.")
def doctor_command(platform: str, dotenv: str, skip_platform: bool) -> None:
    """Perform read-only configuration and platform checks."""
    config = _config(platform, dotenv, require_workspace=not skip_platform)
    errors = config.validate(require_gateway=True, require_send_status=True)
    errors.extend(legacy_state_issues(config))
    errors.extend(legacy_profile_issues(BrowserProfile(config.browser_profile_root, platform)))
    database = inspect_database(config.state_db)
    if not database["creatable"]:
        errors.append("adapter SQLite state is unavailable or its parent is not writable")
    if database["exists"] and database["schema_version"] not in {3, 4, 5, 6}:
        errors.append(f"unsupported adapter SQLite schema: {database['schema_version']}")
    if database["exists"] and database["integrity"] != "ok":
        errors.append(f"adapter SQLite integrity check failed: {database['integrity']}")
    if database["exists"] and inspect_state_slot_count(config.state_db, config.platform) > 1:
        errors.append("state database contains multiple legacy account_key slots; explicit reset is required")
    unowned_outbox = inspect_unowned_outbox_count(config.state_db)
    if unowned_outbox:
        errors.append(
            f"{unowned_outbox} legacy outbox event(s) have no platform Actor ownership; "
            "they are blocked until the platform is archived/reset"
        )
    checks: dict[str, Any] = {
        "platform": config.platform,
        "rabbitmq_configured": not any("RABBITMQ" in e or "EDGE2IM" in e or "IM2EDGE" in e for e in errors),
        "rabbitmq_connected": None,
        "receive_queue": "",
        "send_status_configured": config.send_status_success is not None and config.send_status_failed is not None,
        "send_rate_limit": {
            "min_interval_seconds": config.send_min_interval_seconds,
            "jitter_seconds": config.send_jitter_seconds,
            "max_per_minute": config.send_max_per_minute,
            "max_per_hour": config.send_max_per_hour,
        },
        "state_parent_exists": config.state_db.parent.exists(),
        "state_parent_writable": database["creatable"],
        "sqlite": database,
        "unowned_outbox_count": unowned_outbox,
        "platform_authenticated": None,
        "platform_actor_id": "",
        "errors": errors,
    }

    credentials = CredentialStore(config.credential_db, read_only=True)
    if credentials.legacy_account_count(config.platform) > 1:
        checks["errors"].append("multiple legacy credential account_key slots require explicit reset")

    async def verify() -> None:
        try:
            await probe_rabbitmq(config)
            checks["rabbitmq_connected"] = True
        except Exception as exc:
            checks["rabbitmq_connected"] = False
            checks["errors"].append(f"RabbitMQ passive check failed: {type(exc).__name__}: {exc}")
        adapter = create_platform_adapter(
            config.platform,
            credentials=credentials,
            browser_profile_root=config.browser_profile_root,
        )
        try:
            actor = await adapter.authenticate()
            await adapter.validate_identity(actor)
            state_uid = inspect_actor_binding(config.state_db, config.platform)
            if state_uid and state_uid != actor.platform_actor_id:
                raise RuntimeError(
                    f"state is bound to platform_actor_id={state_uid}; authenticated UID={actor.platform_actor_id}"
                )
            checks["platform_authenticated"] = True
            checks["platform_actor_id"] = actor.platform_actor_id
            checks["receive_queue"] = config.receive_queue_name(actor.platform_actor_id)
        except Exception as exc:
            checks["platform_authenticated"] = False
            checks["errors"].append(f"platform authentication failed: {exc}")
        finally:
            await adapter.close()
            pass

    if not skip_platform:
        asyncio.run(verify())
    if platform == "douyin":
        try:
            from message_adapter.platforms.douyin.signing import probe_signing_runtime

            checks["douyin_signing"] = probe_signing_runtime()
            if not checks["douyin_signing"].get("ok"):
                checks["errors"].append(
                    "douyin signing runtime unavailable: "
                    + str(checks["douyin_signing"].get("error_type") or checks["douyin_signing"].get("error") or "unknown")
                )
        except Exception as exc:  # noqa: BLE001
            checks["douyin_signing"] = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:300]}
            checks["errors"].append(f"douyin signing probe failed: {type(exc).__name__}")
    if platform == "rednote":
        try:
            from message_adapter.platforms.rednote.signing import probe_signing_runtime

            checks["rednote_runtime"] = probe_signing_runtime()
            if not checks["rednote_runtime"].get("ok"):
                checks["errors"].append(
                    "rednote runtime unavailable: "
                    + str(
                        checks["rednote_runtime"].get("error_type")
                        or checks["rednote_runtime"].get("error")
                        or "unknown"
                    )
                )
        except Exception as exc:  # noqa: BLE001
            checks["rednote_runtime"] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
            }
            checks["errors"].append(f"rednote runtime probe failed: {type(exc).__name__}")
    credentials.close()
    click.echo(json.dumps({"ok": not checks["errors"], "schema_version": "4", "data": checks}, indent=2, ensure_ascii=False))
    if checks["errors"]:
        raise SystemExit(1)


@cli.command("mq-watch")
@click.option("--platform", type=click.Choice(["boss", "douyin", "rednote"]), required=True)
@click.option("--dotenv", default=".env", show_default=True, type=click.Path(dir_okay=False))
@click.option("--seconds", default=60, show_default=True, type=click.IntRange(1, 3600))
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, 1000))
@click.option("--platform-actor-id", default="", help="Optionally observe only one platform Actor UID.")
@click.option("--all-platforms", is_flag=True, help="Do not filter by the selected platform.")
def mq_watch_command(
    platform: str,
    dotenv: str,
    seconds: int,
    limit: int,
    platform_actor_id: str,
    all_platforms: bool,
) -> None:
    """Safely observe new IM-to-edge events without stealing shared messages."""
    config = _config(platform, dotenv)
    errors = config.validate(require_gateway=True, require_send_status=False)
    if errors:
        _echo_errors(errors)
        raise click.ClickException("RabbitMQ configuration is incomplete")

    async def run() -> int:
        count = 0
        finished = asyncio.Event()

        async def show(payload: dict[str, Any]) -> None:
            nonlocal count
            if not all_platforms and str(payload.get("platform") or "") != platform:
                return
            if platform_actor_id and str(payload.get("platform_actor_id") or "") != platform_actor_id:
                return
            count += 1
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            if count >= limit:
                finished.set()

        watcher = asyncio.create_task(watch_rabbitmq(config, show), name="rabbitmq-watch")
        timer = asyncio.create_task(asyncio.sleep(seconds), name="rabbitmq-watch-timeout")
        limit_waiter = asyncio.create_task(finished.wait(), name="rabbitmq-watch-limit")
        try:
            done, _ = await asyncio.wait(
                (watcher, timer, limit_waiter),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if watcher in done:
                exc = watcher.exception()
                if exc:
                    raise exc
            return count
        finally:
            for task in (watcher, timer, limit_waiter):
                task.cancel()
            await asyncio.gather(watcher, timer, limit_waiter, return_exceptions=True)

    click.echo(
        f"Watching new events on {config.receive_exchange}/{config.receive_routing_key} "
        f"for {seconds}s (temporary queue; no platform sends)...",
        err=True,
    )
    try:
        count = asyncio.run(run())
    except Exception as exc:
        raise click.ClickException(f"RabbitMQ watch failed: {type(exc).__name__}: {exc}") from exc
    click.echo(f"mq-watch finished: {count} matching message(s)", err=True)


def _parse_since(value: str) -> int:
    text = value.strip()
    if text.isdigit():
        raw = int(text)
        return raw if raw > 10_000_000_000 else raw * 1000
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


@cli.command("backfill")
@click.option("--platform", type=click.Choice(["boss", "douyin", "rednote"]), required=True)
@click.option("--since", required=True, help="Unix timestamp or ISO-8601 time.")
@click.option("--limit", required=True, type=click.IntRange(1, 1000))
@click.option("--dry-run", is_flag=True)
@click.option("--dotenv", default=".env", show_default=True, type=click.Path(dir_okay=False))
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation when enqueueing.")
def backfill_command(
    platform: str,
    since: str,
    limit: int,
    dry_run: bool,
    dotenv: str,
    yes: bool,
) -> None:
    """Inspect or enqueue a bounded historical message replay."""
    try:
        cursor = str(_parse_since(since))
    except (ValueError, OverflowError) as exc:
        raise click.BadParameter("must be Unix seconds/milliseconds or ISO-8601", param_hint="--since") from exc
    config = _config(platform, dotenv, require_workspace=True)
    if not dry_run and not yes:
        click.confirm(f"Enqueue up to {limit} historical messages for the next adapter run?", abort=True)
    with _workspace_manager_lock(), SingleInstanceLock(config.owner_lock_path):
        profile = BrowserProfile(config.browser_profile_root, platform)
        profile_errors = legacy_profile_issues(profile)
        if profile_errors:
            raise click.ClickException("; ".join(profile_errors))
        migrate_legacy_state_database(config)
        migrate_legacy_browser_profile(profile)
        store = SQLiteStore(config.state_db)
        credentials = CredentialStore(config.credential_db)
        adapter = create_platform_adapter(
            config.platform,
            credentials=credentials,
            browser_profile_root=config.browser_profile_root,
        )
        if not adapter.capabilities.history_backfill:
            store.close()
            credentials.close()
            raise click.ClickException(f"{platform} history access is disabled")

        async def collect() -> tuple[str, list[dict[str, Any]]]:
            try:
                actor = await adapter.authenticate()
                messages = (await adapter.catch_up(cursor))[:limit]
                payloads: list[dict[str, Any]] = []
                for message in messages:
                    payload = message.mq_payload(actor)
                    payloads.append(payload)
                    if not dry_run:
                        await asyncio.to_thread(store.save_conversation, message.conversation)
                        await asyncio.to_thread(store.enqueue, str(payload["id"]), payload)
                return actor.platform_actor_id, payloads
            finally:
                await adapter.close()

        try:
            platform_actor_id, payloads = asyncio.run(collect())
        finally:
            store.close()
            credentials.close()
    click.echo(
        json.dumps(
            {
                "ok": True,
                "schema_version": "4",
                "data": {
                    "platform": platform,
                    "platform_actor_id": platform_actor_id,
                    "dry_run": dry_run,
                    "count": len(payloads),
                    "messages": payloads if dry_run else [],
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )


cli.add_command(boss)
cli.add_command(douyin)


if __name__ == "__main__":
    cli()
