@echo off
REM Buy with AI — Windows setup. Zero-budget: no paid APIs, no keys.
REM Mirrors scripts/setup.sh. Run from the project root.
setlocal
cd /d "%~dp0.."

python scripts\check-env.py
if errorlevel 1 (
  echo [FAIL] Environment check failed. Fix the missing prerequisites above.
  exit /b 1
)

if not exist "backend\.venv" (
  echo Creating Python virtual environment in backend\.venv...
  python -m venv backend\.venv
  if errorlevel 1 (
    echo [FAIL] Could not create the virtual environment. Is Python 3.11+ installed?
    exit /b 1
  )
)

echo Installing Python backend dependencies...
call backend\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
if errorlevel 1 (
  echo [FAIL] pip install failed.
  exit /b 1
)

echo Installing frontend dependencies...
pushd frontend
call npm install
if errorlevel 1 (
  echo [FAIL] npm install failed.
  popd
  exit /b 1
)
popd

if not exist "backend\.env" (
  copy /y backend\.env.example backend\.env >nul
  echo Created backend\.env from .env.example (no secrets needed).
)

echo Seeding price baselines (labelled estimates, not live prices)...
REM Use the venv Python directly: the root seed wrapper looks for a
REM Unix-style .venv/bin/python path, which does not exist on Windows.
backend\.venv\Scripts\python.exe backend\scripts\seed-baselines.py
if errorlevel 1 (
  echo [WARN] Seeding failed. You can retry it later with: backend\.venv\Scripts\python.exe backend\scripts\seed-baselines.py
)

echo.
echo Setup complete! Run 'scripts\start-dev.bat' to launch Buy with AI.
endlocal
