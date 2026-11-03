#!/usr/bin/env python3
"""Seed the SQLite price-baseline table (project-root wrapper).

Delegates to backend/scripts/seed-baselines.py using the backend virtual
environment when present. Baselines are labelled estimates, not live prices.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
VENV_PY = os.path.join(BACKEND, ".venv", "bin", "python")
SEED = os.path.join(BACKEND, "scripts", "seed-baselines.py")

python = VENV_PY if os.path.exists(VENV_PY) else sys.executable
raise SystemExit(
    subprocess.run([python, SEED], cwd=BACKEND, check=False).returncode
)
