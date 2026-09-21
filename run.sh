#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 Python 3。请检查 Python 是否已加入 PATH。" >&2
  exit 1
fi

"$PYTHON_BIN" "$SCRIPT_DIR/ecnu_calendar.py" "$@"
