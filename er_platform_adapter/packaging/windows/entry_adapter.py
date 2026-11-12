import os
import logging
import sys
from pathlib import Path


def _prepare_frozen_runtime() -> None:
    """Frozen-CLI bootstrap: UTF-8 stdio + work from the exe's own directory."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    if getattr(sys, "frozen", False):
        # 把 exe 所在目录作为工作目录：.env 与 adapter_data/ 都放在 exe 旁边即可，
        # 无论从哪里双击/调用都保持一致。
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        try:
            os.chdir(exe_dir)
        except OSError:
            pass
        # Prefer system Chrome; Playwright driver is bundled inside _MEIPASS.
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")


def _load_dotenv_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _require_runtime_config() -> None:
    """Fail fast with a clear Chinese message when the frozen app cannot work."""
    dotenv = Path(".env")
    if not dotenv.is_file():
        raise SystemExit(
            "缺少 .env 配置文件。\n"
            f"请把 .env 放到与 adapter.exe 同一目录：\n  {Path.cwd()}\n"
            "填好 RabbitMQ 与 Gateway 后再双击运行。"
        )
    values = _load_dotenv_values(dotenv)

    def get(name: str) -> str:
        return os.environ.get(name, values.get(name, "")).strip()

    missing: list[str] = []
    if not get("RABBITMQ_HOST"):
        missing.append("RABBITMQ_HOST")
    if not get("RABBITMQ_USER"):
        missing.append("RABBITMQ_USER")
    if not get("RABBITMQ_PASSWORD"):
        missing.append("RABBITMQ_PASSWORD")
    if missing:
        raise SystemExit(
            " .env 配置不完整，缺少: " + ", ".join(missing) + "\n"
            "请用记事本编辑同目录 .env 后重新双击 adapter.exe。"
        )


def _pause_if_double_clicked() -> None:
    """Keep the console visible when the user double-clicked the exe."""
    if not getattr(sys, "frozen", False):
        return
    try:
        input("\n按回车键关闭窗口…")
    except EOFError:
        pass


_prepare_frozen_runtime()

if len(sys.argv) > 1 and sys.argv[1] == "_restart-guard":
    from message_adapter.restart_guard import guard_main

    raise SystemExit(guard_main(sys.argv[2:]))

from message_adapter.observability import configure_logging  # noqa: E402

configure_logging(False)

# 双击 exe（不带参数）时默认启动桌面连接器，自动打开浏览器。
_double_clicked = len(sys.argv) == 1
if _double_clicked:
    sys.argv.append("serve")

_informational_command = any(arg in {"--help", "--version"} for arg in sys.argv[1:])

if not _informational_command:
    try:
        _require_runtime_config()
    except SystemExit as exc:
        logging.getLogger("message_adapter.startup").error(
            "startup configuration failed: %s",
            exc,
            exc_info=True,
        )
        print(exc, file=sys.stderr)
        if _double_clicked:
            _pause_if_double_clicked()
        raise

print("=" * 50)
print("轻回桌面连接器")
print(f"工作目录: {Path.cwd()}")
print("说明:")
print("  1. 同一激活码工作区同一时间只在一台电脑运行")
print("  2. 本机需安装 Google Chrome")
print("  3. 打开 http://127.0.0.1:8765/ 先用激活码登录本地账号，再登录平台")
print("=" * 50)

from message_adapter.cli import cli  # noqa: E402

if __name__ == "__main__":
    try:
        cli()
    except SystemExit:
        if _double_clicked:
            _pause_if_double_clicked()
        raise
    except BaseException as exc:
        logging.getLogger("message_adapter.crash").exception("adapter process failed")
        print(f"\n启动/运行失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        if _double_clicked:
            _pause_if_double_clicked()
        raise SystemExit(1) from exc
