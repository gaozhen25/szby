from __future__ import annotations

import asyncio
import faulthandler
from importlib import metadata
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform as platform_module
import re
import sys
import threading
import traceback
from datetime import datetime, timezone
import uuid
import zipfile
from typing import Any


RUN_ID = uuid.uuid4().hex
LOG_DIR = Path("adapter_data/logs")
LOG_PATH = LOG_DIR / "adapter.jsonl"
_FATAL_STREAM = None
_FATAL_PATH: Path | None = None

_SENSITIVE_KEYS = (
    "cookie",
    "ticket",
    "private_key",
    "active_code",
    "activation_code",
    "authorization",
    "password",
    "access_key",
    "sessionid",
    "token",
)


def redact_text(value: Any, *, limit: int = 32_000) -> str:
    text = str(value or "")
    if any(key in text.lower() for key in _SENSITIVE_KEYS):
        # Preserve useful context around ordinary messages while hiding common
        # key=value and JSON secret fields.
        text = re.sub(
            r"(?i)(cookie|ticket|private_key|active_code|activation_code|authorization|password|"
            r"access_key|sessionid|token)(\s*[=:]\s*|\"\s*:\s*\")([^\s,&\"}]+)",
            r"\1\2***",
            text,
        )
    text = re.sub(r"(amqps?://)[^:/\s]+:[^@\s]+@", r"\1***:***@", text, flags=re.IGNORECASE)
    text = re.sub(
        r"([?&](?:token|access_key|sessionid|ticket)=)[^&\s]+",
        r"\1***",
        text,
        flags=re.IGNORECASE,
    )
    return text[:limit]


class JsonFormatter(logging.Formatter):
    def __init__(self, *, include_traceback: bool = False):
        super().__init__()
        self.include_traceback = include_traceback

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": redact_text(record.getMessage(), limit=4_000),
            "run_id": RUN_ID,
            "pid": os.getpid(),
            "thread": record.threadName,
        }
        for key in ("platform", "platform_actor_id", "event_id", "client_msg_id"):
            value = getattr(record, key, "")
            if value:
                payload[key] = redact_text(value, limit=256)
        if record.exc_info and record.exc_info[1] is not None:
            err_obj = record.exc_info[1]
            payload["error_type"] = type(err_obj).__name__
            payload["error"] = redact_text(str(err_obj).strip() or repr(err_obj), limit=2_000)
            if self.include_traceback:
                payload["traceback"] = redact_text(
                    "".join(traceback.format_exception(*record.exc_info)),
                    limit=32_000,
                )
        activity = getattr(record, "adapter_activity", None)
        if isinstance(activity, dict):
            payload["activity"] = {
                "platform": redact_text(activity.get("platform"), limit=32),
                "direction": redact_text(activity.get("direction"), limit=32),
                "sender_name": redact_text(activity.get("sender_name"), limit=120),
                "sender_id": redact_text(activity.get("sender_id"), limit=256),
                "content": redact_text(activity.get("content"), limit=1_000),
            }
        return json.dumps(payload, ensure_ascii=False)


class _ActivityFilter(logging.Filter):
    def __init__(self, *, include: bool):
        super().__init__()
        self.include = include

    def filter(self, record: logging.LogRecord) -> bool:
        is_activity = isinstance(getattr(record, "adapter_activity", None), dict)
        return is_activity if self.include else not is_activity


class ActivityFormatter(logging.Formatter):
    PLATFORM_LABELS = {"boss": "BOSS", "douyin": "抖音", "rednote": "小红书"}
    RESET = "\033[0m"
    INCOMING_HEADER = "\033[1;96m"
    INCOMING_CONTENT = "\033[1;93m"
    OUTGOING_HEADER = "\033[1;95m"
    OUTGOING_CONTENT = "\033[1;92m"

    def __init__(self, *, use_color: bool):
        super().__init__()
        self.use_color = use_color

    @staticmethod
    def _safe(value: Any, limit: int) -> str:
        text = str(value or "").replace("\r\n", " ↵ ").replace("\r", " ↵ ").replace("\n", " ↵ ")
        text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text).strip()
        return text[:limit]

    def format(self, record: logging.LogRecord) -> str:
        item = getattr(record, "adapter_activity", {})
        platform = self.PLATFORM_LABELS.get(str(item.get("platform") or ""), str(item.get("platform") or "未知平台"))
        incoming = item.get("direction") != "outgoing"
        direction = "收到" if incoming else "发出"
        icon = "▶" if incoming else "◀"
        sender = self._safe(item.get("sender_name"), 120) or "未知用户"
        sender_id = self._safe(item.get("sender_id"), 256) or "-"
        content = self._safe(item.get("content"), 1000)
        line = f"{icon} {platform} {direction}｜{sender}（UID {sender_id}）：{content}"
        if not self.use_color:
            return line
        header = self.INCOMING_HEADER if incoming else self.OUTGOING_HEADER
        body = self.INCOMING_CONTENT if incoming else self.OUTGOING_CONTENT
        prefix, separator, text = line.partition("：")
        return f"{header}{prefix}{separator}{self.RESET}{body}{text}{self.RESET}"


def activity_color_enabled() -> bool:
    if os.environ.get("FORCE_COLOR", "").strip() not in ("", "0"):
        return True
    if os.environ.get("CLICOLOR_FORCE", "").strip() not in ("", "0"):
        return True
    if "NO_COLOR" in os.environ:
        return False
    return sys.stderr.isatty()


def configure_logging(verbose: bool, *, log_dir: Path | str = LOG_DIR) -> Path:
    global _FATAL_PATH, _FATAL_STREAM
    target = Path(log_dir)
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass
    log_path = target / "adapter.jsonl"
    log_path.touch(exist_ok=True)
    try:
        os.chmod(log_path, 0o600)
    except OSError:
        pass

    console = logging.StreamHandler()
    console._adapter_owned = True  # type: ignore[attr-defined]
    console.addFilter(_ActivityFilter(include=False))
    console.setFormatter(JsonFormatter())
    activity = logging.StreamHandler()
    activity._adapter_owned = True  # type: ignore[attr-defined]
    activity.addFilter(_ActivityFilter(include=True))
    activity.setFormatter(ActivityFormatter(use_color=activity_color_enabled()))
    persisted = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
        delay=True,
    )
    persisted._adapter_owned = True  # type: ignore[attr-defined]
    persisted.setFormatter(JsonFormatter(include_traceback=True))
    root = logging.getLogger()
    for existing in root.handlers:
        if getattr(existing, "_adapter_owned", False):
            existing.close()
    root.handlers[:] = [console, activity, persisted]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    fatal_path = (target / "fatal.log").resolve()
    if _FATAL_STREAM is not None and _FATAL_PATH != fatal_path:
        try:
            faulthandler.disable()
        except RuntimeError:
            pass
        _FATAL_STREAM.close()
        _FATAL_STREAM = None
        _FATAL_PATH = None
    if _FATAL_STREAM is None:
        _FATAL_STREAM = (target / "fatal.log").open("a", encoding="utf-8")
        _FATAL_PATH = fatal_path
        try:
            os.chmod(target / "fatal.log", 0o600)
        except OSError:
            pass
        try:
            faulthandler.enable(file=_FATAL_STREAM, all_threads=True)
        except (OSError, RuntimeError):
            pass

    def log_unhandled(exc_type, exc_value, exc_traceback):  # noqa: ANN001
        logging.getLogger("message_adapter.crash").critical(
            "unhandled process exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = log_unhandled
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: log_unhandled(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
        )
    return log_path.resolve()


def install_asyncio_exception_logging(loop: asyncio.AbstractEventLoop) -> None:
    def handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        error = context.get("exception")
        message = context.get("message") or (type(error).__name__ if error else "unknown")
        logging.getLogger("message_adapter.asyncio").error(
            "unhandled asyncio task error: %s",
            message,
            exc_info=(type(error), error, error.__traceback__) if error else None,
        )

    loop.set_exception_handler(handler)


def diagnostic_bundle(
    *,
    state: dict[str, Any],
    dotenv: str,
    log_dir: Path | str = LOG_DIR,
) -> bytes:
    safe_state = json.loads(json.dumps(state, ensure_ascii=False))
    activation = safe_state.get("activation")
    if isinstance(activation, dict):
        activation["activation_code"] = "***" if activation.get("activation_code") else ""
    local_account = safe_state.get("local_account")
    if isinstance(local_account, dict):
        local_account["activation_code"] = "***" if local_account.get("activation_code") else ""
    keys: set[str] = set()
    dotenv_path = Path(dotenv)
    if dotenv_path.is_file():
        for raw in dotenv_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                keys.add(line.split("=", 1)[0].strip())
    relevant = sorted(
        key for key in keys | set(os.environ) if key.startswith(("ADAPTER_", "RABBITMQ_", "IM2EDGE_", "MQ_", "OSS_"))
    )
    packages = {}
    for package in ("message-adapter", "aio-pika", "playwright", "cryptography", "xhshow", "websocket-client"):
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = "missing"
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "python": sys.version,
        "platform": platform_module.platform(),
        "executable": Path(sys.executable).name,
        "frozen": bool(getattr(sys, "frozen", False)),
        "packages": packages,
        "configured_keys": relevant,
        "state": safe_state,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        target = Path(log_dir)
        for path in sorted(target.glob("adapter.jsonl*")):
            if path.is_file():
                archive.write(path, f"logs/{path.name}")
        fatal = target / "fatal.log"
        if fatal.is_file():
            archive.write(fatal, f"logs/{fatal.name}")
    return output.getvalue()
