#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x "venv/bin/python" ]; then
  python3 -m venv venv
fi

venv/bin/python -m pip install -r backend/requirements.txt

if [ "$#" -eq 0 ]; then
  set -- --port 8003
fi

venv/bin/python -m uvicorn backend.main:app --reload "$@"
