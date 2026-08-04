#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"

python3 scripts/generate_demo.py

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -U pip
  pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

uvicorn weather_copy_bot.api.app:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

cd dashboard
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run dev -- --host 0.0.0.0 --port 5173
