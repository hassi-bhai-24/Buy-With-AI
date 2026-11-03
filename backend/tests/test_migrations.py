"""Alembic migration tests: a fresh empty DB upgrades to the full schema.

Runs the real ``init_db`` (alembic upgrade head) against a temp file DB
via the DATABASE_URL env override, in a subprocess so settings are
re-read. The subprocess approach mirrors production startup exactly.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "alembic_version",
    "chat_messages",
    "chat_threads",
    "checks",
    "deal_journal",
    "price_baselines",
    "project_items",
    "projects",
    "users",
    "watchlist_items",
}


def test_fresh_db_migrates_to_full_schema(tmp_path):
    db_path = tmp_path / "fresh.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    env = dict(os.environ, DATABASE_URL=url, PYTHONPATH=str(BACKEND_DIR))
    code = "import asyncio; from app.database import init_db; asyncio.run(init_db())"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        version = conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
    finally:
        conn.close()
    assert EXPECTED_TABLES <= tables, tables
    assert len(version) == 1
