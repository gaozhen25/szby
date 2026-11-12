# shellcheck shell=bash
# 供飞书巡检脚本 source：解析 ROOT 下的 Python（优先 .venv）。
# 调用方须先设置 ROOT。

_feishu_resolve_python() {
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  elif [[ -x /home/ubuntu/miniconda3/envs/starx/bin/python ]]; then
    PYTHON=/home/ubuntu/miniconda3/envs/starx/bin/python
  elif command -v conda >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate starx
    PYTHON="$(command -v python)"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON="$(command -v python)"
  else
    echo "[$(date '+%F %T')] python not found" >&2
    return 127
  fi
}
