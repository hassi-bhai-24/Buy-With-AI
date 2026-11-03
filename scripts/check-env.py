#!/usr/bin/env python3
"""Cross-platform environment diagnostic for Buy with AI (zero-budget stack).

Checks: Python >= 3.11, Node.js >= 18, SQLite WAL support, Ollama daemon
(optional — the rule-based engine works without it) and Tesseract (optional).
Exit 0 unless a blocking prerequisite is missing. Ollama problems are WARN,
never FAIL, because verdicts fall back to the labelled rule-based engine.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request

OK, WARN, FAIL = "[ OK ]", "[WARN]", "[FAIL]"
failures = []


def check(label, ok, detail=""):
    print(f"{OK if ok else FAIL} {label} {detail}")
    if not ok:
        failures.append(label)


def warn(label, detail=""):
    print(f"{WARN} {label} {detail}")


def main() -> int:
    print("Buy with AI — environment check")
    print("=" * 40)

    check("Python >= 3.11", sys.version_info >= (3, 11),
          f"(found {sys.version.split()[0]})")

    node = shutil.which("node")
    node_ok = False
    if node:
        out = subprocess.run([node, "-v"], capture_output=True, text=True)
        ver = out.stdout.strip().lstrip("v")
        parts = ver.split(".")
        node_ok = len(parts) >= 2 and (int(parts[0]), int(parts[1])) >= (18, 0)
        check("Node.js >= 18", node_ok, f"(found {ver})")
    else:
        check("Node.js >= 18", False, "(not found on PATH)")

    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(os.path.join(tmp, "walcheck.db"))
            conn.execute("PRAGMA journal_mode=WAL;")
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            conn.close()
        check("SQLite WAL support", mode.lower() == "wal", f"(mode={mode})")
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        check("SQLite WAL support", False, f"({exc})")

    # Ollama is optional: rule-based engine is the fallback.
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=3
        ) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in tags.get("models", [])]
        print(f"{OK} Ollama daemon reachable (models: {', '.join(models) or 'none'})")
        if not any(m.startswith("llama3.1") for m in models):
            warn("llama3.1 model", "not found. Run 'ollama pull llama3.1:8b' "
                 "for Ollama reasoning; rule-based engine will be used meanwhile.")
    except Exception:  # noqa: BLE001 - daemon simply absent
        warn("Ollama daemon", "not reachable at http://127.0.0.1:11434. "
             "Start it with 'ollama serve' for LLM reasoning; "
             "the rule-based engine will be used meanwhile.")

    if shutil.which("tesseract"):
        print(f"{OK} Tesseract OCR (optional) found")
    else:
        warn("Tesseract OCR (optional)", "not found. Receipt OCR is not "
             "implemented in this build; safe to ignore.")

    print("=" * 40)
    if failures:
        print(f"BLOCKING PROBLEMS: {', '.join(failures)}")
        return 1
    print("Environment OK. Run './scripts/start-dev.sh' to launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
