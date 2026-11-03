#!/usr/bin/env bash
# Buy with AI — Linux/macOS setup. Zero-budget: no paid APIs, no keys.
set -e
cd "$(dirname "$0")/.."

python3 scripts/check-env.py

if [ ! -d "backend/.venv" ]; then
  echo "Creating Python virtual environment in backend/.venv..."
  python3 -m venv backend/.venv
fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate
echo "Installing Python backend dependencies..."
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "Installing frontend dependencies..."
(cd frontend && npm install)

if [ ! -f "backend/.env" ]; then
  cp backend/.env.example backend/.env
  echo "Created backend/.env from .env.example (no secrets needed)."
fi

echo "Seeding price baselines (labelled estimates, not live prices)..."
python3 scripts/seed-baselines.py

echo ""
echo "Setup complete! Run './scripts/start-dev.sh' to launch Buy with AI."
