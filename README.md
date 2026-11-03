# Buy with AI

An objective, skeptical companion that tells you whether a purchase, inventory
order, or money decision is worth it **before** you commit cash. Decision-first:
a 5-tier verdict (Great Buy, Good Buy, Think Twice, Risky, Avoid), hard numbers,
red flags, and next steps — no essay chat.

Built from the spec set in `~/workspace/documents-project/Documents/`
(see `NOTES.md` for the doc inventory and resolved contradictions).
Zero-budget architecture: local inference, open-source scraping, SQLite.

## Quick start

Requirements: Python 3.11+, Node.js 18+, and (optional) Ollama.

```bash
# 1. Check your environment (Ollama missing is a warning, not an error)
python3 scripts/check-env.py

# 2. Install everything and seed price baselines
./scripts/setup.sh

# 3. Run backend (:8000) + frontend (:3000) together
./scripts/start-dev.sh
```

Then open **http://localhost:3000**.

On Windows, use `scripts\setup.bat` and `scripts\start-dev.bat` instead
(same steps; Windows execution was not verified in this build environment).

With Docker (build/run not verified here — no Docker in the build
environment; see BUILD-REPORT.md):

```bash
docker compose up --build
# Frontend: http://localhost:3000 (nginx, /api proxied to backend)
# First run only — seed baselines inside the backend container:
docker compose exec backend python scripts/seed-baselines.py
```

Run the pieces separately if you prefer:

```bash
# Backend (from backend/)
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend (from frontend/)
npm install
npm run dev        # http://localhost:3000, /api proxied to :8000
npm run build      # production build (includes the CSP meta tag)
npm run test:e2e   # Playwright E2E (starts seeded dev servers itself)
```

Database schema is managed by Alembic (`backend/alembic/`): startup runs
`alembic upgrade head`. To create a new migration after changing models:

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "describe change"
```

Tests: `cd backend && .venv/bin/python -m pytest -q` (184 tests).

### Ollama (optional, local LLM reasoning)

```bash
ollama serve
ollama pull llama3.1:8b
```

With Ollama running, the backend tries it first (JSON mode, temperature 0.1,
Pydantic-validated). Any failure falls back to the deterministic rule-based
engine, and rule-based price bands and cash-flow numbers always win. Without
Ollama, every verdict is rule-based and says so. The Ollama path has **not**
been tested against a live daemon in this build (none was available); verify
on a machine with Ollama before relying on `engine: "ollama"` output.

## How a verdict is made

1. **Scrape attempt** — DuckDuckGo HTML search (allow-listed host only, 8 s
   timeout) for live price samples near your city.
2. **Baseline fallback** — if scraping fails or is throttled, the most recent
   SQLite baseline for the item/city is used.
3. **Estimate fallback** — if no baseline exists, a band is estimated around
   your asking price and labelled as an estimate with Low confidence.
4. **Rules** — deterministic heuristics from the spec: price-band tiers,
   spoilage decay curves for perishables, vehicle mileage/paint penalties,
   land price-per-Marla parity, installment APR, counter-offer brackets,
   and scam-pattern detection (advance-token, urgency, no-inspection).

Every response carries two honest labels:

- `engine`: `"rule-based"` or `"ollama"` — what produced the verdict.
- `price_source`: `"live scrape"`, `"baseline"`, or `"estimate"` — where the
  price figures came from. Baseline figures are cached/seed estimates, never
  presented as live market prices.

## API (base: `http://127.0.0.1:8000/api/v1`)

| Endpoint | Purpose |
|---|---|
| `POST /analyze` | Verdict (sync). Rate-limited: 30/min per IP. |
| `POST /analyze/stream` | Verdict over SSE, 5 progress steps. |
| `GET /checks`, `GET /checks/{id}`, `DELETE /checks/{id}`, `POST /checks/{id}/pin` | Decision history (SQLite). List returns `{items, total}` only. |
| `GET /checks/{id}/share`, `GET /checks/{id}/summary?format=txt\|md` | Share text + downloadable summary. |
| `POST /journal`, `GET /journal/stats` | Deal outcomes + cumulative savings. |
| `POST /tools/margin`, `/tools/convert-land`, `/tools/installment-audit`, `/tools/brand-markup`, `/tools/savings-goal`, `/tools/expense-leakage`, `/tools/discount-validator`, `/tools/currency-convert` | Deterministic calculators (all 8). Currency conversion uses Frankfurter live rates and errors honestly when the service or currency is unavailable — Frankfurter does not support PKR. |
| `GET /geo/geocode?q=...` | Nominatim place lookup (lat/lon + display name). |
| `GET /barcode/{digits}` | Open Food Facts product lookup (EAN-8/13 check-digit validated). |
| `POST /watchlist`, `GET /watchlist`, `DELETE /watchlist/{id}`, `POST /watchlist/{id}/recheck` | Price watchlist (in-app flags only). |
| `POST /chat/threads`, `GET /chat/threads`, `GET/POST /chat/threads/{id}/messages` | Multi-turn chat threads, grounded in a linked check when given. Replies are labelled with their engine. |
| `POST /images/upload` | Image upload with EXIF/GPS stripping (multipart `file`, max 5 MB). OCR text is returned only when Tesseract is installed on the server; otherwise the response says so honestly. |
| `GET /health`, `GET /baselines` | Engine status, seeded/live baselines. |

`POST /analyze` body: `description`, `asking_price` (total for `quantity`
units), `currency` (PKR/USD/INR/GBP/EUR/AED), `country`, `province`, `city`,
`quantity`, `unit`, `category` (`retail`/`vehicle`/`property`/`perishable`/
`inventory`/`business`/`other`), plus optional `seller_notes`, `days_to_sell`,
`temperature_c`, `area_marla`, `marla_standard` (`225`/`272`), `private_mode`
(private checks are never saved).

Interactive docs: `http://127.0.0.1:8000/docs` (FastAPI).

## Architecture

```bash
frontend/   React 19 + TypeScript + Vite + Tailwind CSS v4 (dark stone/emerald, light mode, motion animations, sliding drawer)
backend/    FastAPI + SQLAlchemy 2.0 async + SQLite (WAL, Alembic migrations) + httpx scrapers/integrations
            + Ollama client + rule-based verdict engine + EXIF pipeline (Pillow)
scripts/    check-env.py, setup.sh, start-dev.sh, setup.bat, start-dev.bat, seed-baselines.py
e2e/        Playwright tests (frontend/e2e/) + GitHub Actions CI (.github/workflows/ci.yml)
docker/     backend/Dockerfile, frontend/Dockerfile + nginx.conf, docker-compose.yml
```

The database file `backend/buy_with_ai.db` is created on first run and seeded
with 126 baselines by `scripts/seed-baselines.py`.

## Honest limits — read this before trusting a verdict

- **Rule-based by default here.** Ollama was not available in the build
  environment, so all verified verdicts are rule-based. The engine label on
  every response tells you which one ran.
- **Prices are mostly baselines/estimates.** Live scraping is best-effort and
  frequently throttled; seed baselines are estimates (story numbers from the
  spec where given, plausible values elsewhere), each labelled as such.
  Verify any large decision against real sellers in your own market.
- **Spoilage math is aggressive by design.** The spec's decay curve
  (λ = 0.055/hr above 32 °C) makes multi-day tomato lots at summer heat look
  very bad. It models worst-case ambient exposure, not refrigerated storage.
- **APR formula vs test-plan number.** The spec's constant-ratio APR formula
  gives ~98% for the documented installment example (165,000 cash / 20,000
  down / 18,500 × 12), not the ~42% quoted in the test plan. The formula was
  implemented as written; see BUILD-REPORT.md.
- **Marla standard.** The "272" standard uses 272.0 sq ft (5 Marla = 1,360 sq
  ft) to match the test plan; the official revenue figure is 272.25 sq ft,
  available as standard `"272.25"`.
- **Not built in this pass:** voice input, admin dashboard, offline PWA
  caching, biometric/PIN lock, crowdsourced prices. PDF export is the
  browser print flow (print stylesheet), not a generated PDF binary.
  The UI does not fake any of these. See BUILD-REPORT.md for the full list.
- **Integrations are best-effort and honestly labelled.** Geocoding,
  barcode, and currency lookups run server-side with timeouts and
  fallbacks; when a service is unreachable the API errors instead of
  inventing data. In the build sandbox the services were unreachable
  from server code (no direct egress), so the in-app success paths
  are unverified there — verify on a machine with direct internet.
  Frankfurter (ECB rates) does not support PKR, so PKR conversions
  return an honest error rather than a rate.
- **Not financial or legal advice.** Verdicts are estimates from limited data.
  Property checklist items (Patwari/Fard/NOC) must be verified in person at
  the land office. Nothing here is a substitute for inspection or counsel.
- **Untested:** real phone use, real Ollama daemon, real DuckDuckGo
  scraping at scale (sandbox network limits), Docker build/run,
  Windows `.bat` execution, CI runs on GitHub, and the Tesseract OCR
  path (no Tesseract in the build environment). Playwright E2E (14
  tests) does pass in Chromium against real dev servers.

## Security / privacy

- No API keys, secrets, or accounts anywhere in the code or config.
- Scraper fetches only the allow-listed DuckDuckGo HTML endpoint with a
  timeout; user-supplied URLs are never fetched (SSRF-safe by construction).
- All inputs are Pydantic-validated; the verdict endpoint is rate-limited.
- Scraped/user text is delimiter-wrapped before any LLM call and can never
  override verdict rules; injection attempts are flagged, never obeyed.
- Guest mode only: no email, password, or tracking. History lives in the
  local SQLite file; DELETE removes the row and runs `incremental_vacuum`.
  Private checks bypass storage entirely.
- Device-UUID history is a local device identity mechanism, NOT secure
  authentication, and anyone with the UUID can read that device's history.
