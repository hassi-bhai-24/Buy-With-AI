#!/usr/bin/env bash
# Buy with AI — concurrent dev runner: backend :8000 + frontend :3000.
# Ollama is optional; if it is not running, the backend uses the rule-based
# engine and labels every verdict accordingly.
set -e
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT INT TERM

if ! curl -fs -m 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "[WARN] Ollama is not running on port 11434."
  echo "       Start it with 'ollama serve' (+ 'ollama pull llama3.1:8b') for LLM reasoning."
  echo "       Continuing with the rule-based engine."
fi

if [ -d "backend/.venv" ]; then
  # shellcheck disable=SC1091
  source backend/.venv/bin/activate
fi
(cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload) &
(cd frontend && npm run dev) &

echo "Buy with AI is starting:"
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://127.0.0.1:8000/api/v1/health"
echo "Press Ctrl+C to stop all services."
wait
