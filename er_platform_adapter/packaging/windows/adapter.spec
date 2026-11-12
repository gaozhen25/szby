# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PC-side `adapter` CLI (one-file Windows exe).

Run inside the cross-build container with /src = repository root.
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

SRC = str(Path(os.environ.get("ADAPTER_SOURCE_ROOT", Path.cwd().parent)).resolve())

datas = [
    # Web control page assets, served via importlib.resources.
    (f"{SRC}/message_adapter/web/index.html", "message_adapter/web"),
    (f"{SRC}/message_adapter/web/app.css", "message_adapter/web"),
    (f"{SRC}/message_adapter/web/app.js", "message_adapter/web"),
    (f"{SRC}/message_adapter/web/小主机启动企业微信.docx", "message_adapter/web"),
    (f"{SRC}/message_adapter/web/小主机启动个人微信.docx", "message_adapter/web"),
    (f"{SRC}/message_adapter/web/logos/boss.png", "message_adapter/web/logos"),
    (f"{SRC}/message_adapter/web/logos/douyin.png", "message_adapter/web/logos"),
    (f"{SRC}/message_adapter/web/logos/wechat.svg", "message_adapter/web/logos"),
    (f"{SRC}/message_adapter/web/logos/wecom.png", "message_adapter/web/logos"),
    (f"{SRC}/message_adapter/web/logos/rednote.png", "message_adapter/web/logos"),
    # Douyin signing script, read via a __file__-relative path.
    (f"{SRC}/message_adapter/platforms/douyin/vendor/douyin.js", "message_adapter/platforms/douyin/vendor"),
]
# Playwright driver (node.exe + JS driver) — required to launch Chrome.
datas += collect_data_files("playwright", includes=["driver/**"])
datas += copy_metadata("playwright")
# aio_pika/aiormq/pamqp read their own version via importlib.metadata at
# runtime ("No package metadata was found for aio-pika" if missing).
datas += copy_metadata("aio-pika")
datas += copy_metadata("aiormq")
datas += copy_metadata("pamqp")
datas += copy_metadata("cryptography")
datas += copy_metadata("xhshow")
datas += copy_metadata("websocket-client")
binaries = collect_dynamic_libs("cryptography")

hiddenimports = (
    collect_submodules("aio_pika")
    + collect_submodules("aiormq")
    + collect_submodules("pamqp")
    + collect_submodules("paho")
    + collect_submodules("execjs")
    + collect_submodules("websockets")
    + collect_submodules("httpx")
    + collect_submodules("ecdsa")
    + collect_submodules("cryptography")
    + collect_submodules("xhshow")
    + collect_submodules("websocket")
    + [
        "playwright.async_api",
        "certifi",
        "multidict",
        "yarl",
        "propcache",
        "frozenlist",
        "idna",
        "charset_normalizer",
    ]
)

a = Analysis(
    ["entry_adapter.py"],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="adapter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
