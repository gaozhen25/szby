"""Shared output primitives for platform command groups."""

from __future__ import annotations

import json
from typing import Any

import click

from message_adapter.config import AdapterConfig
from message_adapter.process_lock import SingleInstanceLock
from message_adapter.workspaces import active_workspace_root


def active_adapter_config(platform: str, dotenv: str) -> AdapterConfig:
    root = active_workspace_root()
    if root is None:
        raise click.ClickException("请先启动 adapter serve 并在网页中登录本地激活码账号")
    return AdapterConfig.load(platform=platform, dotenv=dotenv, data_root=root)


def active_workspace_manager_lock() -> SingleInstanceLock:
    root = active_workspace_root()
    if root is None:
        raise click.ClickException("请先启动 adapter serve 并在网页中登录本地激活码账号")
    return SingleInstanceLock(root.parent.parent / ".locks" / "workspace-manager.lock")


def emit_json(platform: str, data: Any, *, ok: bool = True) -> None:
    """Write the stable JSON envelope used by every platform command."""
    click.echo(
        json.dumps(
            {"ok": ok, "platform": platform, "data": data},
            ensure_ascii=False,
            indent=2,
        )
    )
