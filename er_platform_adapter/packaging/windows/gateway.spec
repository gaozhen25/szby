# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the server-side `adapter-gateway` CLI (one-file Windows exe).

Run inside the cross-build container with /src = repository root.
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

SRC = str(Path(os.environ.get("ADAPTER_SOURCE_ROOT", Path.cwd().parent)).resolve())

# pydantic_core ships a native _pydantic_core DLL that must be collected explicitly.
binaries = collect_dynamic_libs("pydantic_core")
datas = collect_data_files("pydantic_core")

hiddenimports = (
    collect_submodules("grpc")
    + collect_submodules("google.protobuf")
    + ["grpc._cython.cygrpc", "uvicorn.logging", "uvicorn.loops", "uvicorn.protocols"]
)

a = Analysis(
    ["entry_gateway.py"],
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
    name="adapter-gateway",
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
