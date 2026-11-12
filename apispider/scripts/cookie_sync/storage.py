"""Cookie 池的本地安全写入与远程原子上传。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


HOST_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]+$")
REMOTE_PATH_PATTERN = re.compile(r"^~/[A-Za-z0-9_./-]+$")


def build_pool(
    extracted: dict[str, list[str]], output: Path, *, allow_partial: bool
) -> dict[str, list[str]]:
    missing = [platform for platform in ("xhs", "dy") if not extracted[platform]]
    if missing and not allow_partial:
        raise ValueError(f"未找到平台登录态: {', '.join(missing)}")

    existing: dict[str, object] = {}
    if output.is_file():
        try:
            loaded = json.loads(output.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    pool: dict[str, list[str]] = {}
    for platform in ("xhs", "dy"):
        previous = existing.get(platform, [])
        fallback = previous if isinstance(previous, list) else []
        pool[platform] = extracted[platform] or fallback
    previous_ks = existing.get("ks", [])
    pool["ks"] = previous_ks if isinstance(previous_ks, list) else []
    return pool


def atomic_write_pool(output: Path, pool: dict[str, list[str]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".cookies.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(pool, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def upload_pool(output: Path, host: str, remote_path: str) -> None:
    if not HOST_PATTERN.fullmatch(host):
        raise ValueError("SSH 主机名包含非法字符")
    if not REMOTE_PATH_PATTERN.fullmatch(remote_path) or ".." in remote_path.split("/"):
        raise ValueError("远程路径必须是 ~/ 下的安全路径")

    remote_dir, remote_name = remote_path.rsplit("/", 1)
    remote_temp = f"{remote_dir}/.{remote_name}.upload-{os.getpid()}"
    try:
        subprocess.run(
            ["scp", "-q", str(output), f"{host}:{remote_temp}"], check=True
        )
        command = (
            f"umask 077 && mkdir -p {remote_dir} && chmod 600 {remote_temp} "
            f"&& mv -f {remote_temp} {remote_path}"
        )
        subprocess.run(["ssh", host, command], check=True)
    except subprocess.CalledProcessError:
        subprocess.run(
            ["ssh", host, f"rm -f {remote_temp}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        raise

