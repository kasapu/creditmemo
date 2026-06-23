#!/usr/bin/env bash
# One-command launcher: creates a venv, installs deps, then starts the server.
#
#   ./run.sh            # offline / mock mode
#   ./run.sh --azure    # also install Azure deps + Playwright Chromium
#   ./run.sh --seed     # seed a sample AAPL dataset before starting
#
# Env overrides: PORT (default 8001), HOST (default 127.0.0.1)
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV=".venv"
WANT_AZURE=0
WANT_SEED=0

for arg in "$@"; do
  case "$arg" in
    --azure) WANT_AZURE=1 ;;
    --seed)  WANT_SEED=1 ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

if [ ! -d "$VENV" ]; then
  echo "==> Creating virtualenv ($VENV)"
  "$PYTHON" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "==> Installing core dependencies"
pip install --upgrade pip -q
pip install -r requirements.txt -q

if [ "$WANT_AZURE" -eq 1 ]; then
  echo "==> Installing Azure dependencies + Playwright Chromium"
  pip install -r requirements-azure.txt -q
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
