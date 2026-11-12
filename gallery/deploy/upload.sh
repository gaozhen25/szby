#!/usr/bin/env bash
# Upload gallery to a remote host and start docker compose on port 1880.
# Usage:
#   REMOTE=ubuntu@115.29.200.91 bash deploy/upload.sh
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE="${REMOTE:?set REMOTE like ubuntu@115.29.200.91}"
DIR="${REMOTE_DIR:-/opt/gallery}"

ssh -o BatchMode=yes "$REMOTE" "sudo mkdir -p '$DIR' && sudo chown -R \$(whoami):\$(whoami) '$DIR'"

rsync -az --delete \
  --exclude '.venv/' \
  --exclude '.git/' \
  --exclude 'data/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude '.ref-fast-soy-admin/' \
  --exclude '.api.log' \
  --exclude '.api.pid' \
  --exclude '1.json' \
  ./ "$REMOTE:$DIR/"

# Keep server .env if it already exists; otherwise copy local .env once.
ssh "$REMOTE" "test -f '$DIR/.env' || true"
if ssh "$REMOTE" "test ! -f '$DIR/.env'"; then
  if [[ -f .env ]]; then
    scp .env "$REMOTE:$DIR/.env"
  else
    echo "missing .env; create $DIR/.env on the server before starting" >&2
    exit 1
  fi
fi

ssh "$REMOTE" "cd '$DIR' && (command -v docker >/dev/null || { echo 'docker missing on server' >&2; exit 1; }) && docker compose up -d --build && docker compose ps"

echo "app is behind nginx on ${REMOTE%:*}:1880 — point your domain proxy there"
