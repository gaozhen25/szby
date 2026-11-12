# -*- coding: utf-8 -*-
"""抖音请求签名与 Cookie 解析。"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from execjs._external_runtime import ExternalRuntime
from execjs._external_runtime import node as _execjs_node_runtime

_JS_PATH = Path(__file__).resolve().parent / "vendor" / "douyin.js"
_CTX = None
_NODE_BINARY: str | None = None


def _frozen_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def _meipass() -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def _bundled_node_sources() -> list[Path]:
    """Candidate Node binaries shipped with Playwright / the frozen exe."""
    names = ("node.exe", "node")
    roots: list[Path] = []

    frozen = _frozen_dir()
    if frozen is not None:
        roots.append(frozen)
        roots.append(frozen / "adapter_data" / "runtime")

    try:
        import playwright

        roots.append(Path(playwright.__file__).resolve().parent / "driver")
    except Exception:
        pass

    meipass = _meipass()
    if meipass is not None:
        roots.append(meipass / "playwright" / "driver")
        roots.append(meipass)
        for name in names:
            for hit in meipass.rglob(name):
                if hit.is_file():
                    roots.append(hit.parent)
                    break

    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for name in names:
            candidate = root / name
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
    return out


def _looks_like_node(path: Path) -> bool:
    if not path.is_file():
        return False
    # Ignore tiny stubs / incomplete extracts.
    try:
        if path.stat().st_size < 1_000_000:
            return False
    except OSError:
        return False
    if os.name != "nt" and not os.access(path, os.X_OK):
        return False
    return True


def _materialize_node(source: Path) -> Path:
    """Copy Node out of the onefile temp dir so Windows AV/SmartScreen can run it."""
    frozen = _frozen_dir()
    if frozen is None:
        return source
    if source.parent == frozen or source.parent == frozen / "adapter_data" / "runtime":
        return source

    dest_dir = frozen / "adapter_data" / "runtime"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ("node.exe" if os.name == "nt" or source.suffix.lower() == ".exe" else "node")
    try:
        if not dest.is_file() or dest.stat().st_size != source.stat().st_size:
            shutil.copy2(source, dest)
    except OSError as exc:
        raise RuntimeError(f"无法写出内置 Node 到 {dest}: {exc}") from exc
    return dest


def _probe_node(binary: str) -> None:
    env = os.environ.copy()
    # Playwright's Node refuses Wine/odd kernels; skip only the OS banner check.
    env.setdefault("NODE_SKIP_PLATFORM_CHECK", "1")
    try:
        completed = subprocess.run(
            [binary, "-e", "process.stdout.write('ok')"],
            check=False,
            capture_output=True,
            timeout=15,
            text=True,
            env=env,
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 Node ({binary}): {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Node 启动超时 ({binary})") from exc
    if completed.returncode != 0 or (completed.stdout or "").strip() != "ok":
        detail = (completed.stderr or completed.stdout or "").strip()[:200]
        raise RuntimeError(f"Node 自检失败 ({binary}) rc={completed.returncode} {detail}")


def _resolve_node_binary() -> str:
    global _NODE_BINARY
    if _NODE_BINARY:
        return _NODE_BINARY

    os.environ.setdefault("NODE_SKIP_PLATFORM_CHECK", "1")

    for name in ("node", "nodejs"):
        found = shutil.which(name)
        if found and _looks_like_node(Path(found)):
            _probe_node(found)
            _NODE_BINARY = found
            return found

    last_error: Exception | None = None
    for candidate in _bundled_node_sources():
        if not _looks_like_node(candidate):
            continue
        try:
            binary = str(_materialize_node(candidate))
            _probe_node(binary)
            _NODE_BINARY = binary
            return binary
        except Exception as exc:  # noqa: BLE001 - try next candidate
            last_error = exc
            continue

    hint = f" 上次错误: {last_error}" if last_error else ""
    raise RuntimeError(
        "抖音签名需要 Node，但未找到可用运行时。"
        "请使用最新 adapter.exe（会自动释放内置 Node），"
        "或在同目录放置 node.exe / 安装系统 Node.js。"
        + hint
    )


def _node_runtime() -> ExternalRuntime:
    """Always use Node (never Windows JScript): douyin.js is not JScript-compatible."""
    binary = str(Path(_resolve_node_binary()).resolve())
    template = _execjs_node_runtime()
    # Put Node's directory on PATH and invoke by basename so Windows PATHEXT
    # resolution works. Also force _binary_cache: PyExecJS's _which() appends
    # PATHEXT to absolute paths (C:\\...\\node.exe → node.exe.EXE) and then
    # marks the runtime unavailable, raising empty RuntimeUnavailableError().
    node_dir = str(Path(binary).parent)
    os.environ["PATH"] = node_dir + os.pathsep + os.environ.get("PATH", "")
    command_name = Path(binary).name
    runtime = ExternalRuntime(
        name="Node.js",
        command=command_name,
        runner_source=template._runner_source,
        encoding=template._encoding,
        tempfile=True,
    )
    runtime._binary_cache = [binary]
    runtime._available = True
    return runtime


def _js_source() -> str:
    if _JS_PATH.is_file():
        return _JS_PATH.read_text(encoding="utf-8-sig")
    meipass = _meipass()
    if meipass is not None:
        alt = meipass / "message_adapter" / "platforms" / "douyin" / "vendor" / "douyin.js"
        if alt.is_file():
            return alt.read_text(encoding="utf-8-sig")
    raise FileNotFoundError(f"douyin.js not found at {_JS_PATH}")


def _ctx():
    global _CTX
    if _CTX is None:
        os.environ["EXECJS_RUNTIME"] = "Node"
        _CTX = _node_runtime().compile(_js_source())
    return _CTX


def probe_signing_runtime() -> dict[str, Any]:
    """Read-only check used by `adapter doctor` / packaging smoke tests."""
    info: dict[str, Any] = {"ok": False, "node": "", "sample": ""}
    try:
        binary = _resolve_node_binary()
        info["node"] = binary
        sample = get_a_bogus("a=1", "Mozilla/5.0")
        info["sample"] = sample[:16]
        info["ok"] = bool(sample)
    except Exception as exc:  # noqa: BLE001
        info["error_type"] = type(exc).__name__
        info["error"] = str(exc)[:300]
    return info


def get_web_id() -> str:
    def e(t):
        if t is not None:
            return str(t ^ (int(16 * random.random()) >> (t // 4)))
        return "".join(
            [
                str(int(1e7)),
                "-",
                str(int(1e3)),
                "-",
                str(int(4e3)),
                "-",
                str(int(8e3)),
                "-",
                str(int(1e11)),
            ]
        )

    web_id = "".join(e(int(x)) if x in "018" else x for x in e(None))
    return web_id.replace("-", "")[:19]


def get_a_bogus(query_string: str, user_agent: str, *, uri: str = "") -> str:
    """对已拼好的 query（不含 a_bogus）签名。"""
    name = "sign_reply" if "/reply" in uri else "sign_datail"
    return _ctx().call(name, query_string, user_agent)


def parse_cookie_str(cookie: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def parse_sec_user_id(url_or_id: str) -> str:
    text = (url_or_id or "").strip()
    if not text:
        raise ValueError("空的博主 ID/URL")
    if text.startswith("MS4wLjABAAAA") or (not text.startswith("http") and "douyin.com" not in text):
        return text.split("?")[0]
    m = re.search(r"/user/([^/?]+)", text)
    if m:
        return m.group(1)
    raise ValueError(f"无法解析 sec_user_id: {url_or_id}")


def parse_video_info_from_url(url_or_id: str) -> Dict[str, str]:
    """
    解析作品 URL 或纯 aweme_id。

    支持:
    - 纯数字 ID
    - /video/{id}、/note/{id}
    - ?modal_id=
    - v.douyin.com 短链（url_type=short，需客户端 resolve）
    """
    from urllib.parse import parse_qs, urlparse

    text = (url_or_id or "").strip()
    if not text:
        raise ValueError("空的作品 URL/ID")
    if text.isdigit():
        return {"aweme_id": text, "url_type": "normal"}

    is_short = "v.douyin.com" in text or (text.startswith("http") and len(text) < 50 and "/video/" not in text and "/note/" not in text)
    if is_short:
        return {"aweme_id": "", "url_type": "short"}

    params = parse_qs(urlparse(text).query)
    modal_id = (params.get("modal_id") or [""])[0]
    if modal_id:
        return {"aweme_id": modal_id, "url_type": "modal"}

    match = re.search(r"/(?:video|note)/(\d+)", text)
    if match:
        return {"aweme_id": match.group(1), "url_type": "normal"}

    raise ValueError(f"无法从 URL 解析 aweme_id: {url_or_id}")
