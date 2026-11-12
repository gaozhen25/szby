#!/usr/bin/env bash
# One-shot cross-build from macOS/Linux: builds the Wine+PyInstaller image,
# runs the Windows build, and leaves the exes in <repo>/dist/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "==> building image (first run downloads ~1GB, takes a few minutes)"
# --platform linux/amd64 is required on Apple Silicon: the x86_64 wine build
# is the one that can run the x64 Windows Python toolchain.
docker build --platform linux/amd64 -t adapter-win-build:latest -f packaging/windows/Dockerfile packaging/windows

echo "==> running Windows build inside container"
# The named volume persists the wine prefix (Windows Python + installed deps),
# so re-runs only redo the PyInstaller packaging step.
docker run --rm --platform linux/amd64 \
  -v "$ROOT:/src" \
  -v "$ROOT/packaging/windows:/build" \
  -v adapter-win-prefix:/opt/wine \
  adapter-win-build:latest \
  bash /build/build.sh

echo "==> done. artifacts in $ROOT/build_win/dist/"
ls -lh "$ROOT/build_win/dist/"
