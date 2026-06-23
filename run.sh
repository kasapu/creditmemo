#!/usr/bin/env bash
# One-command launcher: creates a venv, installs deps, then starts the server.
#
#   ./run.sh            # offline / mock mode
#   ./run.sh --azure    # also install Azure deps + Playwright Chromium
#   ./run.sh --seed     # seed a sample AAPL dataset before starting
#
# Requires Python 3.11+. If your system Python is older (e.g. Ubuntu 20.04 ships
# 3.8) and you cannot install a newer one, install `uv` and this script will use
# it to download a self-contained Python 3.11 (works on ARM64 / Snapdragon too):
#   curl -LsSf https://astral.sh/uv/install.sh | sh
#
# Env overrides: PYTHON, PORT (default 8001), HOST (default 127.0.0.1)
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
MIN_MINOR=11   # requires Python 3.11+
WANT_AZURE=0
WANT_SEED=0

for arg in "$@"; do
  case "$arg" in
    --azure) WANT_AZURE=1 ;;
    --seed)  WANT_SEED=1 ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

# True if the given interpreter is Python 3.$MIN_MINOR or newer.
py_ok() {
  "$1" -c "import sys; sys.exit(0 if sys.version_info >= (3, $MIN_MINOR) else 1)" 2>/dev/null
}

# Pick a system interpreter: explicit $PYTHON wins, else probe newest-first.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for cand in python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1 && py_ok "$cand"; then
      PYTHON="$cand"; break
    fi
  done
fi

HAVE_SYS_PY=0
if [ -n "$PYTHON" ] && command -v "$PYTHON" >/dev/null 2>&1 && py_ok "$PYTHON"; then
  HAVE_SYS_PY=1
fi
HAVE_UV=0
command -v uv >/dev/null 2>&1 && HAVE_UV=1

if [ "$HAVE_SYS_PY" -eq 0 ] && [ "$HAVE_UV" -eq 0 ]; then
  echo "ERROR: Python 3.$MIN_MINOR+ is required but was not found." >&2
  echo "Detected: $({ python3 --version 2>&1; } || echo 'no python3')" >&2
  echo "" >&2
  echo "Easiest fix (no sudo, works on ARM64/Snapdragon) -- install uv, then re-run:" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "  source \$HOME/.local/bin/env   # or reopen your terminal" >&2
  echo "  ./run.sh" >&2
  echo "" >&2
  echo "Alternatively, on Ubuntu with sudo:" >&2
  echo "  sudo add-apt-repository ppa:deadsnakes/ppa -y" >&2
  echo "  sudo apt update && sudo apt install -y python3.11 python3.11-venv" >&2
  exit 1
fi

# Recreate the venv if it is missing or was built with an unsupported Python.
if [ -d "$VENV" ] && ! py_ok "$VENV/bin/python"; then
  echo "==> Existing $VENV uses an unsupported Python; recreating"
  rm -rf "$VENV"
fi

if [ ! -d "$VENV" ]; then
  if [ "$HAVE_SYS_PY" -eq 1 ]; then
    echo "==> Creating virtualenv with $("$PYTHON" --version 2>&1) ($PYTHON)"
    "$PYTHON" -m venv "$VENV"
  else
    echo "==> No system Python 3.$MIN_MINOR+; using uv to fetch Python 3.$MIN_MINOR"
    uv venv --python "3.$MIN_MINOR" "$VENV"
  fi
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Use uv for installs when the venv has no pip (uv-created venvs omit pip).
if [ -x "$VENV/bin/pip" ]; then
  PIP="pip"
  pip install --upgrade pip -q
else
  PIP="uv pip"
fi

echo "==> Installing core dependencies ($PIP)"
$PIP install -r requirements.txt -q

if [ "$WANT_AZURE" -eq 1 ]; then
  echo "==> Installing Azure dependencies + Playwright Chromium"
  $PIP install -r requirements-azure.txt -q
  python -m playwright install chromium
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
fi

if [ "$WANT_SEED" -eq 1 ]; then
  echo "==> Seeding sample AAPL dataset"
  PYTHONPATH=. python scripts/seed_sample.py
fi

echo "==> Starting server on http://${HOST:-127.0.0.1}:${PORT:-8001}"
exec python run.py
