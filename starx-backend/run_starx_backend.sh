#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/projects/starx-backend
port="$(/home/ubuntu/miniconda3/envs/starx/bin/python -c 'from app.core.config import settings; print(settings.port)')"
exec /home/ubuntu/miniconda3/envs/starx/bin/uvicorn app.main:app --host 0.0.0.0 --port "${port}"
