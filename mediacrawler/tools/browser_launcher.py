# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/browser_launcher.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


import os
import platform
import subprocess
import time
import socket
import signal
from typing import Optional, List, Tuple
import asyncio
from pathlib import Path

from tools import utils


class BrowserLauncher:
    """
    Browser launcher for detecting and launching user's Chrome/Edge browser
    Supports Windows and macOS systems
    """

    def __init__(self):
        self.system = platform.system()
        self.browser_process = None
        self.debug_port = None

    def detect_browser_paths(self) -> List[str]:
        """
        Detect available browser paths in system
        Returns list of browser paths sorted by priority
        """
        paths = []

        if self.system == "Windows":
            # Common Chrome/Edge installation paths on Windows
            possible_paths = [
                # Chrome paths
                os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                # Edge paths
                os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
                # Chrome Beta/Dev/Canary
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome Beta\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome Dev\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome SxS\Application\chrome.exe"),
            ]
        elif self.system == "Darwin":  # macOS
            # Common Chrome/Edge installation paths on macOS
            possible_paths = [
                # Chrome paths
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
                "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",
                "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
                # Edge paths
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta",
                "/Applications/Microsoft Edge Dev.app/Contents/MacOS/Microsoft Edge Dev",
                "/Applications/Microsoft Edge Canary.app/Contents/MacOS/Microsoft Edge Canary",
            ]
        else:
            # Linux and other systems
            possible_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/google-chrome-beta",
                "/usr/bin/google-chrome-unstable",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
                "/snap/bin/chromium",
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
                "/usr/bin/microsoft-edge-beta",
                "/usr/bin/microsoft-edge-dev",
            ]

        # Check if path exists and is executable
        for path in possible_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                paths.append(path)

        return paths

    def find_available_port(self, start_port: int = 9222) -> int:
        """
        Find available port
        """
        port = start_port
        while port < start_port + 100:  # Try up to 100 ports
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
                    return port
            except OSError:
                port += 1

        raise RuntimeError(f"Cannot find available port, tried {start_port} to {port-1}")

    @staticmethod
    def get_system_chrome_user_data_dir(browser_path: str = "") -> str:
        """
        本机日常 Chrome / Edge 的用户数据目录（含 Cookie、登录态）。
        """
        home = Path.home()
        path_lower = (browser_path or "").lower()
        prefer_edge = "edge" in path_lower or "msedge" in path_lower

        if platform.system() == "Darwin":
            if prefer_edge:
                return str(home / "Library/Application Support/Microsoft Edge")
            return str(home / "Library/Application Support/Google/Chrome")
        if platform.system() == "Windows":
            local = os.environ.get("LOCALAPPDATA", "")
            if prefer_edge:
                return os.path.join(local, "Microsoft", "Edge", "User Data")
            return os.path.join(local, "Google", "Chrome", "User Data")
        # Linux
        if prefer_edge:
            return str(home / ".config/microsoft-edge")
        chrome = home / ".config/google-chrome"
        if chrome.is_dir():
            return str(chrome)
        return str(home / ".config/chromium")

    @staticmethod
    def get_local_chrome_clone_dir() -> str:
        """
        Chrome 150+ 禁止在默认 Profile 上开远程调试，需克隆到非默认目录。
        """
        path = os.path.join(os.getcwd(), "browser_data", "cdp_local_chrome_user_data_dir")
        os.makedirs(path, exist_ok=True)
        return path

    @classmethod
    def sync_system_profile_to_clone(
        cls, browser_path: str = "", *, clone_dir: Optional[str] = None
    ) -> str:
        """
        把日常 Chrome Profile 同步到项目内克隆目录（排除缓存/锁文件）。
        返回克隆目录路径，可作为 --user-data-dir 启动 CDP。
        """
        import shutil

        src = cls.get_system_chrome_user_data_dir(browser_path)
        dst = clone_dir or cls.get_local_chrome_clone_dir()
        if not os.path.isdir(src):
            raise RuntimeError(f"未找到日常浏览器用户目录: {src}")

        ignore_names = {
            "SingletonLock",
            "SingletonCookie",
            "SingletonSocket",
            "RunningChromeVersion",
            "ChromeFeatureState",
            "lockfile",
        }
        ignore_dir_names = {
            "Cache",
            "Code Cache",
            "GPUCache",
            "ShaderCache",
            "GrShaderCache",
            "GraphiteDawnCache",
            "Service Worker",
            "Crashpad",
            "BrowserMetrics",
            "optimization_guide_model_store",
            "component_crx_cache",
            "extensions_crx_cache",
        }

        utils.logger.info(
            f"[BrowserLauncher] Syncing system Chrome profile → clone for CDP\n"
            f"  from: {src}\n"
            f"  to:   {dst}"
        )
        # 清理旧锁，避免克隆目录残留占用
        for lock_name in (
            "SingletonLock",
            "SingletonCookie",
            "SingletonSocket",
        ):
            lock_path = Path(dst) / lock_name
            try:
                if lock_path.exists() or lock_path.is_symlink():
                    lock_path.unlink()
            except OSError:
                pass

        # copytree dirs_exist_ok：增量覆盖关键文件
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            # 过滤忽略目录（就地改 dirs 以阻止深入）
            dirs[:] = [d for d in dirs if d not in ignore_dir_names and "cache" not in d.lower()]
            target_root = dst if rel == "." else os.path.join(dst, rel)
            os.makedirs(target_root, exist_ok=True)
            for name in files:
                if name in ignore_names or name.endswith(".tmp"):
                    continue
                s = os.path.join(root, name)
                d = os.path.join(target_root, name)
                try:
                    shutil.copy2(s, d)
                except OSError:
                    continue

        utils.logger.info("[BrowserLauncher] System profile sync done")
        return dst

    @staticmethod
    def is_browser_process_running(browser_path: str = "") -> bool:
        """本机是否已有 Chrome/Edge 进程（占用日常 Profile）。"""
        path_lower = (browser_path or "").lower()
        prefer_edge = "edge" in path_lower or "msedge" in path_lower
        system = platform.system()
        try:
            if system == "Darwin":
                names = ["Microsoft Edge"] if prefer_edge else ["Google Chrome"]
                for name in names:
                    r = subprocess.run(
                        ["pgrep", "-x", name],
                        capture_output=True,
                        check=False,
                    )
                    if r.returncode == 0:
                        return True
                return False
            if system == "Windows":
                image = "msedge.exe" if prefer_edge else "chrome.exe"
                r = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {image}"],
                    capture_output=True,
                    text=True,
                    check=False,
                    encoding="utf-8",
                    errors="ignore",
                )
                return image.lower() in (r.stdout or "").lower()
            # Linux
            pattern = "microsoft-edge|msedge" if prefer_edge else "chrome|chromium"
            r = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                check=False,
            )
            return r.returncode == 0
        except Exception:
            return False

    def quit_browser(self, browser_path: str = "", timeout: float = 20.0) -> None:
        """优雅退出本机日常 Chrome/Edge，释放用户目录锁。"""
        path_lower = (browser_path or "").lower()
        prefer_edge = "edge" in path_lower or "msedge" in path_lower
        system = platform.system()
        utils.logger.info("[BrowserLauncher] Quitting system browser to free user profile...")

        try:
            if system == "Darwin":
                app = "Microsoft Edge" if prefer_edge else "Google Chrome"
                subprocess.run(
                    ["osascript", "-e", f'quit app "{app}"'],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                # 残留 Helper 会导致「正在现有的浏览器会话中打开」且不起 CDP
                time.sleep(0.5)
                subprocess.run(
                    ["killall", app],
                    capture_output=True,
                    check=False,
                    timeout=5,
                )
            elif system == "Windows":
                image = "msedge.exe" if prefer_edge else "chrome.exe"
                subprocess.run(
                    ["taskkill", "/IM", image, "/F"],
                    capture_output=True,
                    check=False,
                    encoding="utf-8",
                    errors="ignore",
                )
            else:
                pattern = "microsoft-edge|msedge" if prefer_edge else "chrome|chromium"
                subprocess.run(
                    ["pkill", "-f", pattern],
                    capture_output=True,
                    check=False,
                )
        except Exception as exc:
            utils.logger.warning(f"[BrowserLauncher] Quit browser failed: {exc}")

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_browser_process_running(browser_path):
                utils.logger.info("[BrowserLauncher] System browser has exited")
                time.sleep(1.2)  # 等用户目录锁释放
                return
            time.sleep(0.4)

        utils.logger.warning(
            "[BrowserLauncher] Browser still running after quit; profile may stay locked"
        )

    def launch_browser(
        self,
        browser_path: str,
        debug_port: int,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        *,
        system_profile: bool = False,
    ) -> subprocess.Popen:
        """
        Launch browser process

        system_profile=True 时：不显式传 --user-data-dir（用 Chrome 默认日常目录），
        并减少干扰性参数，避免「正在现有的浏览器会话中打开」后不起 CDP。
        """
        if system_profile:
            # Chrome 150+：远程调试必须用非默认 --user-data-dir
            # 此处传入的应是日常 Profile 的克隆目录
            args = [
                browser_path,
                f"--remote-debugging-port={debug_port}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ]
            if user_data_dir:
                args.append(f"--user-data-dir={user_data_dir}")
        else:
            # Basic launch arguments
            args = [
                browser_path,
                f"--remote-debugging-port={debug_port}",
                "--remote-debugging-address=0.0.0.0",  # Allow remote access
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=TranslateUI",
                "--disable-ipc-flooding-protection",
                "--disable-hang-monitor",
                "--disable-prompt-on-repost",
                "--disable-sync",
                "--disable-dev-shm-usage",  # Avoid shared memory issues
                "--no-sandbox",  # Disable sandbox in CDP mode
                # Key anti-detection arguments
                "--disable-blink-features=AutomationControlled",  # Disable automation control flag
                "--exclude-switches=enable-automation",  # Exclude automation switch
                "--disable-infobars",  # Disable info bars
            ]

        # Headless mode
        if headless:
            args.extend([
                "--headless=new",  # Use new headless mode
                "--disable-gpu",
            ])
        elif not system_profile:
            # Extra arguments for non-headless mode
            args.extend([
                "--start-maximized",  # Maximize window, more like real user
            ])

        # User data directory（非 system_profile 时在此附加）
        if user_data_dir and not system_profile:
            args.append(f"--user-data-dir={user_data_dir}")

        utils.logger.info(f"[BrowserLauncher] Launching browser: {browser_path}")
        utils.logger.info(f"[BrowserLauncher] Debug port: {debug_port}")
        utils.logger.info(f"[BrowserLauncher] Headless mode: {headless}")
        if system_profile:
            utils.logger.info(
                f"[BrowserLauncher] System profile clone CDP: user-data-dir={user_data_dir}"
            )

        try:
            # On Windows, use CREATE_NEW_PROCESS_GROUP to prevent Ctrl+C from affecting subprocess
            if self.system == "Windows":
                process = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                process = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=os.setsid  # Create new process group
                )

            self.browser_process = process
            return process

        except Exception as e:
            utils.logger.error(f"[BrowserLauncher] Failed to launch browser: {e}")
            raise

    def wait_for_browser_ready(self, debug_port: int, timeout: int = 30) -> bool:
        """
        Wait for browser to be ready
        """
        utils.logger.info(f"[BrowserLauncher] Waiting for browser to be ready on port {debug_port}...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            # 子进程若秒退（交给已有会话），尽早失败并打出 stderr
            if self.browser_process and self.browser_process.poll() is not None:
                err = ""
                try:
                    _, stderr = self.browser_process.communicate(timeout=1)
                    err = (stderr or b"").decode("utf-8", errors="ignore").strip()
                except Exception:
                    pass
                utils.logger.error(
                    "[BrowserLauncher] Browser process exited before CDP was ready"
                    + (f": {err}" if err else "")
                )
                return False

            try:
                # 强制 IPv4，避免 localhost → ::1 而 Chrome 只监听 127.0.0.1
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    result = s.connect_ex(("127.0.0.1", debug_port))
                    if result == 0:
                        utils.logger.info(f"[BrowserLauncher] Browser is ready on port {debug_port}")
                        return True
            except Exception:
                pass

            time.sleep(0.5)

        utils.logger.error(f"[BrowserLauncher] Browser failed to be ready within {timeout} seconds")
        return False

    def get_browser_info(self, browser_path: str) -> Tuple[str, str]:
        """
        Get browser info (name and version)
        """
        try:
            if "chrome" in browser_path.lower():
                name = "Google Chrome"
            elif "edge" in browser_path.lower() or "msedge" in browser_path.lower():
                name = "Microsoft Edge"
            elif "chromium" in browser_path.lower():
                name = "Chromium"
            else:
                name = "Unknown Browser"

            # Try to get version info
            try:
                result = subprocess.run([browser_path, "--version"],
                                      capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=5)
                version = result.stdout.strip() if result.stdout else "Unknown Version"
            except:
                version = "Unknown Version"

            return name, version

        except Exception:
            return "Unknown Browser", "Unknown Version"

    def cleanup(self):
        """
        Cleanup resources, close browser process
        """
        if not self.browser_process:
            return

        process = self.browser_process

        if process.poll() is not None:
            utils.logger.info("[BrowserLauncher] Browser process already exited, no cleanup needed")
            self.browser_process = None
            return

        utils.logger.info("[BrowserLauncher] Closing browser process...")

        try:
            if self.system == "Windows":
                # First try normal termination
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    utils.logger.warning("[BrowserLauncher] Normal termination timeout, using taskkill to force kill")
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True,
                        check=False,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    process.wait(timeout=5)
            else:
                pgid = os.getpgid(process.pid)
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    utils.logger.info("[BrowserLauncher] Browser process group does not exist, may have exited")
                else:
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        utils.logger.warning("[BrowserLauncher] Graceful shutdown timeout, sending SIGKILL")
                        os.killpg(pgid, signal.SIGKILL)
                        process.wait(timeout=5)

            utils.logger.info("[BrowserLauncher] Browser process closed")
        except Exception as e:
            utils.logger.warning(f"[BrowserLauncher] Error closing browser process: {e}")
        finally:
            self.browser_process = None
