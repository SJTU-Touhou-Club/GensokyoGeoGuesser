#!/usr/bin/env bash
# One-line installer: pip deps, npm deps, asset copy, frontend build, data check.
#   ./install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SYS_PY="${PYTHON:-python3}"
VENV="$ROOT/.venv"

# Create virtualenv if it does not exist yet.
if [ ! -f "$VENV/bin/python" ]; then
    echo "[venv] Creating virtualenv at $VENV ..."
    "$SYS_PY" -m venv "$VENV"
fi

PY="$VENV/bin/python"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"

echo "[1/5] Installing Python dependencies (index: $PIP_INDEX_URL)..."
"$PY" -m pip install --upgrade pip -i "$PIP_INDEX_URL"
"$PY" -m pip install -r requirements.txt -i "$PIP_INDEX_URL"

echo "[2/5] Installing frontend dependencies..."
npm --prefix frontend install

echo "[3/5] Copying data assets into static/..."
"$PY" scripts/copy_static_assets.py

echo "[4/5] Building frontend..."
npm --prefix frontend run build

echo "[5/5] Verifying dataset and locations..."
"$PY" scripts/verify_data.py

echo
echo "Install complete. Start the server with: $PY app.py"
