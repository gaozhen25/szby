"""Restart a packaged connector after it exits."""

from __future__ import annotations

import os
import subprocess
import sys
import time


def should_restart(exit_code: int) -> bool:
    """Any observed exit starts the connector again."""
    del exit_code
    return True


def guard_process_args(executable: str, pid: int) -> list[str]:
    return [executable, "_restart-guard", "--pid", str(pid)]


def arm_restart_guard() -> None:
    """Start a detached watcher. Only the packaged serve process does this."""
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("ADAPTER_WATCHDOG") == "1":
        return
    if "--no-restart" in sys.argv:
        return
    executable = os.path.abspath(sys.executable)
    env = os.environ.copy()
    env["ADAPTER_WATCHDOG"] = "1"
    kwargs: dict[str, object] = {
        "cwd": os.path.dirname(executable),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    subprocess.Popen(guard_process_args(executable, os.getpid()), **kwargs)  # noqa: S603


def wait_exit_code(pid: int) -> int | None:
    """Block until the connector process ends and return its exit code."""
    if os.name != "nt" or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    query = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize | query, False, pid)
    if not handle:
        return None
    try:
        if kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) != 0:
            return None
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return int(code.value)
    finally:
        kernel32.CloseHandle(handle)


def launch_connector(executable: str) -> None:
    env = os.environ.copy()
    env.pop("ADAPTER_WATCHDOG", None)
    kwargs: dict[str, object] = {
        "cwd": os.path.dirname(os.path.abspath(executable)),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([executable], **kwargs)  # noqa: S603


def guard_main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "--pid":
        return 2
    try:
        pid = int(argv[1])
    except ValueError:
        return 2
    exit_code = wait_exit_code(pid)
    if exit_code is None or not should_restart(exit_code):
        return 0
    time.sleep(2)
    launch_connector(os.path.abspath(sys.executable))
    return 0
