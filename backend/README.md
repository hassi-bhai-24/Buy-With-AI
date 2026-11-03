# Buy with AI — Backend

FastAPI + SQLAlchemy 2.0 async + SQLite (WAL). Deterministic rule-based
verdict engine is primary; an Ollama client is tried first only when the
local Ollama daemon is reachable, with fallback to the rule-based engine.
Every verdict labels `engine` (`"rule-based"` / `"ollama"`) and
`price_source` (`"live scrape"` / `"baseline"` / `"estimate"`). Live
prices are never invented: the only live source is the DuckDuckGo HTML
search page (`https://html.duckduckgo.com/html/`); on any failure the
SQLite baseline table is used, and with neither, an estimate band is
derived from the asking price and labelled as such.

No user-supplied URLs are fetched in v1: URLs in a description are
ignored (never fetched, never cited).

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/seed-baselines.py   # 100+ baselines, labelled estimates
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The database file defaults to `backend/buy_with_ai.db` (override with
`DATABASE_URL`). CORS allows `http://localhost:3000` and
`http://127.0.0.1:3000`.

## Tests

```bash
.venv/bin/pytest -q
```

Tests use a temporary SQLite file and mock the scraper/Ollama clients,
so no network or Ollama daemon is required.

## Notes / known deviations from the spec documents

- Land conversion: the `lahore_272` standard uses a marla factor of
  exactly 272.0 sq ft (5 marla = 1360.0 sq ft, per the test plan). The
  revenue standard 272.25 sq ft is available as standard `"272.25"`.
- Installment APR uses the constant-ratio formula exactly as documented
  in the heuristics doc. For the test-plan example (cash 165000, down
  20000, 18500 x 12) that formula yields ~98% APR, not the ~42% quoted
  in the test plan; the formula is implemented as written.
- Ollama is not available in the build sandbox, so all verdicts there
  are rule-based. The Ollama path is implemented and validated, and is
  exercised only when a daemon answers `/api/tags`.
