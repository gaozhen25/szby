#!/usr/bin/env bash
# Cross-build the Windows one-file exes inside the container.
# /src   = repository root (bind mount)
# /build = packaging/windows (bind mount)
#
# Notes:
# - Uses the embeddable Windows Python (zip) instead of the GUI installer —
#   reliable under headless Wine.
# - On Apple Silicon the image must be built/run with --platform linux/amd64
#   (Rosetta), because only the x86_64 wine can run the x64 Windows toolchain.
set -euo pipefail

export WINEARCH=win64
export WINEPREFIX=/opt/wine
export WINEDEBUG=-all
export PYTHONDONTWRITEBYTECODE=1
export ADAPTER_SOURCE_ROOT='Z:\src'

if command -v wine64 >/dev/null 2>&1; then
  WINE=wine64
elif command -v wine >/dev/null 2>&1; then
  WINE=wine
elif [ -x /usr/lib/wine/wine64 ]; then
  WINE=/usr/lib/wine/wine64
else
  echo "wine not found" >&2
  exit 1
fi
echo "==> using $WINE ($(command -v "$WINE" || echo "$WINE"))"

# GUI-less wine: wrap every invocation in a virtual display.
run_wine() {
  xvfb-run -a "$WINE" "$@"
}

PYROOT='C:\Python311'
PYEXE="$PYROOT\\python.exe"
PIP_INDEX='https://mirrors.aliyun.com/pypi/simple/'

echo '==> checking Windows Python'
if ! run_wine "$PYEXE" --version >/dev/null 2>&1; then
  echo '==> installing Windows Python 3.11.9 (embeddable, no GUI installer)'
  cd /tmp
  if ! wget -q -T 120 https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-embed-amd64.zip -O python-embed.zip; then
    echo '==> Huawei mirror failed, trying python.org'
    wget -q -T 120 https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip -O python-embed.zip
  fi
  ls -lh python-embed.zip
  mkdir -p "$WINEPREFIX/drive_c/Python311"
  unzip -q -o python-embed.zip -d "$WINEPREFIX/drive_c/Python311"
  # Enable site-packages for the embeddable distribution.
  printf 'python311.zip\n.\nLib\\site-packages\nimport site\n' > "$WINEPREFIX/drive_c/Python311/python311._pth"
  run_wine "$PYEXE" --version
  if ! wget -q -T 120 https://mirrors.aliyun.com/pypi/get-pip.py -O get-pip.py; then
    echo '==> aliyun get-pip failed, trying bootstrap.pypa.io'
    wget -q -T 120 https://bootstrap.pypa.io/get-pip.py -O get-pip.py
  fi
  run_wine "$PYEXE" get-pip.py -i "$PIP_INDEX"
fi
run_wine "$PYEXE" -m pip --version

pip_install() {
  if ! run_wine "$PYEXE" -m pip install -i "$PIP_INDEX" "$@"; then
    echo '==> mirror failed, retrying from pypi.org'
    run_wine "$PYEXE" -m pip install "$@"
  fi
}

echo '==> installing build + runtime dependencies (skipped when already present)'
pip_install -r 'Z:\build\requirements.txt'

echo '==> verifying playwright driver layout'
run_wine "$PYEXE" -c "import os, playwright; d = os.path.join(os.path.dirname(playwright.__file__), 'driver'); print('playwright at', d); print(sorted(os.listdir(d)))"
run_wine "$PYEXE" -c "import execjs; print('execjs runtime:', execjs.get().name)"

echo '==> building adapter.exe'
cd /src
mkdir -p build_win
cp /build/entry_adapter.py /build/adapter.spec /build/entry_gateway.py /build/gateway.spec build_win/
cd build_win
run_wine "$PYEXE" -m PyInstaller --noconfirm --clean --distpath dist --workpath work adapter.spec

# Sidecar Node next to the exe: more reliable than running from PyInstaller _MEIPASS
# on locked-down Windows machines (SmartScreen / AV).
NODE_SRC="$WINEPREFIX/drive_c/Python311/Lib/site-packages/playwright/driver/node.exe"
if [ -f "$NODE_SRC" ]; then
  cp -f "$NODE_SRC" dist/node.exe
  echo "==> bundled sidecar node.exe ($(du -h dist/node.exe | awk '{print $1}'))"
else
  echo "WARNING: playwright driver node.exe not found; Windows signing may fail without system Node" >&2
fi

echo '==> building adapter-gateway.exe (best effort; adapter.exe is the primary deliverable)'
set +e
run_wine "$PYEXE" -m PyInstaller --noconfirm --clean --distpath dist --workpath work gateway.spec
gw_build_rc=$?
set -e
echo "gateway build rc=$gw_build_rc"
if [ "$gw_build_rc" -eq 0 ] && [ -f dist/adapter-gateway.exe ]; then
  GW_PRESENT=1
else
  echo 'WARNING: adapter-gateway.exe build failed; continuing with adapter.exe only'
  GW_PRESENT=0
fi

echo '==> smoke tests (adapter.exe)'
run_wine dist/adapter.exe --version
run_wine dist/adapter.exe --help >/dev/null

# Functional smoke test with a local-only .env (no external services).
# The frozen entry chdirs to the exe directory, so the smoke .env must sit
# next to the exe (this is exactly how the delivered single file is used).
cd /src/build_win/dist
cat > .env <<'EOF'
RABBITMQ_HOST=127.0.0.1
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_PORT=1
ADAPTER_GATEWAY_URL=https://adapter.example.com
EOF
echo '==> doctor --skip-platform (config + sqlite + imports; .env next to exe)'
set +e
doctor_out=$(xvfb-run -a "$WINE" ./adapter.exe doctor --platform boss --skip-platform 2>&1)
doctor_rc=$?
set -e
echo "doctor rc=$doctor_rc"
if ! echo "$doctor_out" | grep -q '"ok": true'; then
  echo 'doctor smoke FAILED' >&2
  echo "$doctor_out" >&2
  exit 1
fi
echo "$doctor_out" | grep -E '"creatable"|"state_parent_writable"|"errors"' | head -3
echo '==> doctor douyin signing probe (uses sidecar/bundled Node)'
set +e
sign_out=$(xvfb-run -a "$WINE" ./adapter.exe doctor --platform douyin --skip-platform 2>&1)
sign_rc=$?
set -e
echo "douyin doctor rc=$sign_rc"
if [ "$sign_rc" -eq 0 ] && echo "$sign_out" | grep -q '"douyin_signing"'; then
  echo "$sign_out" | grep -E '"douyin_signing"|"node"|"sample"' | head -5
else
  echo 'douyin signing doctor FAILED' >&2
  echo "$sign_out" >&2
  exit 1
fi
echo '==> doctor rednote dependency/signing probe'
set +e
rednote_out=$(timeout 45 xvfb-run -a "$WINE" ./adapter.exe doctor --platform rednote --skip-platform 2>&1)
rednote_rc=$?
set -e
echo "rednote doctor rc=$rednote_rc"
if [ "$rednote_rc" -ne 0 ] || ! echo "$rednote_out" | grep -q '"rednote_runtime"'; then
  echo 'rednote runtime doctor FAILED' >&2
  echo "$rednote_out" >&2
  exit 1
fi
echo '==> run --platform boss (single-instance lock; expected to stop at missing credential)'
set +e
run_out=$(timeout 45 xvfb-run -a "$WINE" ./adapter.exe run --platform boss 2>&1 | tail -5)
rc=${PIPESTATUS[0]}
set -e
echo "run rc=$rc"
if ! echo "$run_out" | grep -qE 'BOSS credential missing|already running'; then
  # Rosetta+wine occasionally crashes at process startup (AVX assertion),
  # producing rc=0 with no output. Retry once before failing the build.
  echo 'run smoke output unexpected; retrying once'
  set +e
  run_out=$(timeout 45 xvfb-run -a "$WINE" ./adapter.exe run --platform boss 2>&1 | tail -5)
  rc=${PIPESTATUS[0]}
  set -e
  echo "run retry rc=$rc"
fi
if echo "$run_out" | grep -qE 'BOSS credential missing|already running'; then
  echo 'SMOKE_OK'
else
  echo "run smoke unexpected output: $run_out" >&2
  exit 1
fi

# Remove smoke-test leftovers from the deliverable folder.
rm -f .env /tmp/doctor_out.json
rm -rf adapter_data

if [ "$GW_PRESENT" -eq 1 ]; then
  echo '==> smoke test (adapter-gateway.exe --help, best effort)'
  set +e
  run_wine dist/adapter-gateway.exe --help >/dev/null
  gw_help_rc=$?
  set -e
  echo "gateway --help rc=$gw_help_rc"
fi

echo '==> artifacts'
cp /src/.env.example /src/build_win/dist/.env.example 2>/dev/null || true
cp /build/使用说明.txt /build/启动连接器.bat /src/build_win/dist/ 2>/dev/null || true
ls -lh /src/build_win/dist/

# Stop the wine server so the container exits promptly (wineserver would otherwise keep it alive).
"$WINE" wineserver -k 2>/dev/null || true
