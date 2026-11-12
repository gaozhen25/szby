#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/projects/starx-backend
exec /home/ubuntu/miniconda3/envs/starx/bin/uvicorn app.main:app --host 0.0.0.0 --port 10002
