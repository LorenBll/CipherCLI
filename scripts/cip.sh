#!/bin/sh

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="$ROOT/.venv/bin/python"

if [ -x "$PYTHON" ]; then
  exec "$PYTHON" "$ROOT/src/main.py" "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$ROOT/src/main.py" "$@"
fi

exec python "$ROOT/src/main.py" "$@"