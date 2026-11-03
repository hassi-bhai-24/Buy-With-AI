@echo off
REM Buy with AI — Windows concurrent dev runner: backend :8000 + frontend :3000.
REM Mirrors scripts/start-dev.sh. Ollama is optional; without it the backend
REM uses the rule-based engine and labels every verdict accordingly.
REM Run from the project root. Close this window (or press Ctrl+C in each
REM child window) to stop both services.
setlocal
cd /d "%~dp0.."

curl -fs -m 3 http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
  echo [WARN] Ollama is not running on port 11434.
  echo        Start it with 'ollama serve' (+ 'ollama pull llama3.1:8b') for LLM reasoning.
  echo        Continuing with the rule-based engine.
)

if exist "backend\.venv\Scripts\activate.bat" (
  call backend\.venv\Scripts\activate.bat
)

echo Buy with AI is starting:
echo   Frontend: http://localhost:3000
echo   Backend:  http://127.0.0.1:8000/api/v1/health
echo Close the two new windows to stop both services.

start "Buy with AI - backend" cmd /k "cd /d "%CD%\backend" && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
start "Buy with AI - frontend" cmd /k "cd /d "%CD%\frontend" && npm run dev"

echo Both services launched in separate windows.
endlocal
