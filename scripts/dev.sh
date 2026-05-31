#!/usr/bin/env bash
# Dev bootstrap script: creates venv, installs deps, runs migrations, and starts the server
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT=$(pwd)
VENV_DIR=${VENV_DIR:-venv}
PYTHON=${PYTHON:-python3}
PORT=${PORT:-8003}

echo "Repo root: $REPO_ROOT"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtualenv in $VENV_DIR..."
  $PYTHON -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "Installing backend dependencies..."
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "Running Alembic migrations..."
alembic -c backend/alembic.ini upgrade head || true

echo "Starting Uvicorn on port $PORT... (ctrl-c to stop)"
uvicorn backend.main:app --reload --port "$PORT"
