# Spec notes — Buy with AI

Read 2026-11-03 from `~/workspace/documents-project/Documents/` (23 files, ~336 KB).
All files were read; the five `*_PROMPT.md` pairs are byte-identical to their
non-prompt counterparts (verified by md5: 05, 06, 07, 08, 10).

## Doc inventory

| File | Role (per Guidlines.docx) | What it governed |
|---|---|---|
| 01_PRD.md | Theory | Product scope, 5-tier verdicts, personas, requirements ONB–ADM |
| 02_USER_STORIES.md | Theory | 12 epics, Gherkin acceptance criteria, story numbers (tomato 70–95 PKR/kg; Alto 1.78M/1.87M/1.98M; 5 Marla 220k–350k/Marla) |
| 03_UI_UX_DESIGN_SYSTEM.md | Theory/tokens | Dark stone/emerald tokens, verdict colours, type scale, nested radius law |
| 04_TECHNICAL_ARCHITECTURE.md | Theory | Stack, topology, caching, injection defence, deletion standard |
| 05_API_DOCUMENTATION.md (+ identical _PROMPT) | Prompt doc | FastAPI structure, schemas, endpoints, requirements |
| 06_DATABASE_SCHEMA.md (+ identical _PROMPT) | Prompt doc | SQLite WAL, SQLAlchemy models, ERD |
| 07_README_SETUP.md (+ identical _PROMPT) | Prompt doc | setup.sh, start-dev.sh, check-env.py, seed-baselines.py |
| 08_TEST_PLAN.md (+ identical _PROMPT) | Prompt doc | Pytest/Playwright/adversarial test plan, exact assertions |
| 09_SECURITY_PRIVACY.md | Theory | Threat matrix, injection defence, EXIF, erasure, CSP |
| 10_DEPLOYMENT_CICD.md (+ identical _PROMPT) | Prompt doc | Docker, Compose, Cloudflare Tunnel, GitHub Actions |
| 11_FREE_SERVICES_CHEAT_SHEET.md | Theory/reference | Free services directory, fallback strategy |
| 11_USER_MANUAL.md | User guide | 30-second start, verdict screen, tools, FAQs |
| 12_API_REFERENCE_PROMPT.md | Prompt doc | Alternative endpoint set + TS SDK prompt (see contradictions) |
| 12_EDGE_CASES_HANDBOOK.md | Theory | Fraud patterns: mandi crates, odometer, token scams, 225 vs 272 Marla, offline/429 |
| 13_MARKET_INTELLIGENCE_HEURISTICS.md | Theory | Formulas: spoilage decay, vehicle penalties, land parity, APR, counter-offers, tier boundaries |
| 13_ZERO_BUDGET_FREE_RESOURCES_GUIDE.md | Reference | Free sourcing directory (overlaps 11 cheat sheet) |
| 14_VIBE_CODING_PROMPTS_CATALOG.md | Prompt doc | Modular generation prompts, Modules 1–6 |
| Guidlines.docx | Guide/playbook | Theory vs prompt classification, tool matrix, 5-phase roadmap |

## Contradictions / conflicts found (resolved in favour of theory/reference docs)

1. **Endpoints differ.** 05_API_DOCUMENTATION.md specifies `/api/v1/analyze/stream`,
   `/api/v1/checks`, `/api/v1/journal`, `/api/v1/tools/*`. 12_API_REFERENCE_PROMPT.md
   specifies a different set: `POST /analyze/deal`, `POST /safety/scam-check`,
   `POST /negotiate/script`, with different request/response shapes. Resolution:
   implemented the 05 set as the API; scam-check and negotiation logic are folded
   into the verdict response (red flags + counter-offers) instead of separate
   endpoints. The 12 set is not implemented.
2. **Marla factor.** 13 heuristics give 272.25 sq ft (revenue) and 225 sq ft
   (urban scheme). 08 test plan asserts `convert_marla_to_sqft(5, "lahore_272") == 1360.0`,
   i.e. factor 272.0. Resolution: the "272" standard uses factor 272.0 in code
   (matching the test plan) and the README notes the 272.25 official figure.
3. **Model name.** 04/05 name `llama3.1:8b-instruct-q4_K_M`; 07 check-env looks for
   `llama3.1:8b`. Resolution: `OLLAMA_MODEL` defaults to `llama3.1:8b`; any
   llama3.1 tag is accepted as present by check-env.
4. **Frontend port.** 05 config lists allowed origins on port 3000; 07 topology
   also port 3000. Implemented: Vite on 3000, backend on 8000, Ollama on 11434.
5. **Database URL.** 05/06 show a relative `./buy_with_ai.db` path in one place
   and `sqlite+aiosqlite:///./buy_with_ai.db` in another. Implemented: DB file
   lives in the backend directory, overridable via `DATABASE_URL`.
6. **Motion library.** 03 §6 specifies `motion` (`motion/react`); the build brief
   forbade extra UI/motion libraries. Resolution: CSS transitions/pulse only.
7. **Scope vs single build.** The PRD specifies a very large surface (OCR, barcode,
   voice, chat threads, watchlists, maps, sharing, admin, biometrics). Only the
   core decision product was built in this pass (see BUILD-REPORT.md for the
   exact included/excluded list). Nothing excluded is presented as built.
8. **Prompt docs are generation prompts, not specs.** 05/06/07/08/10/14 contain
   "copy-paste into Cursor" prompt blocks. They were used as implementation
   detail; where they conflicted with theory docs (01–04, 09, 12, 13), theory won.
9. **Seed baseline honesty.** No spec file provides 100+ verified market prices.
   Seed baselines use the documented story numbers where given and clearly
   labelled estimates elsewhere; every response labels its price source.
10. **Motion library (Phase 2).** Contradiction 6 above is superseded:
    the `motion` package (`motion/react`) is now installed and used for
    the drawer, stepper, and verdict-card animations, per doc 03 §6.
11. **Frankfurter / PKR (Phase 2, verified by live probe 2026-11-03).**
    Frankfurter serves ECB reference rates only (~32 currencies,
    including INR/GBP/USD/EUR); PKR is not supported (USD->PKR returns
    HTTP 404). Currency conversion involving PKR therefore returns an
    honest error. No substitute rate source was introduced; the spec's
    TOOL-5 names Frankfurter, and inventing a PKR rate would violate
    the honesty rule.
12. **Geocode coordinates are live-only (Phase 2).** The analyze
    response may carry `coordinates` from Nominatim enrichment; the
    value is not persisted, so history rows return `coordinates: null`.
    No column was added for it.
13. **Checks list shape (Phase 2).** `GET /api/v1/checks` returns only
    `{items, total}` with `total` as the filtered COUNT. The frontend
    strictly requires this shape; the bare-array tolerance is removed.

## Standing honesty rules applied

- Ollama absent in the build sandbox: engine is rule-based, labelled as such.
- No live prices are claimed: price_source is always one of
  "live scrape" / "baseline" / "estimate", and seed baselines are estimates.
- No secrets, keys, or credentials anywhere in the tree (zero-budget design).

## APR resolution (Reliability Hardening — Part 2, 2026-11-03)

Appended, not a rewrite: the earlier APR explanation (contradiction
resolution in this file, the `audit_installment_plan` docstring, and
BUILD-REPORT.md) stays intact. The legacy figure is kept; Part 2 adds
a second, primary figure alongside it. All numbers below were computed
independently by bisection on the cash flows before any code changed.

(a) What the current formula calculates. `apr_percent` is the
constant-ratio approximation: APR = 2 × 12 × I / (P × (n+1)) × 100,
where I = total_paid − cash_price (the finance charge) and
P = cash_price − down_payment (the financed principal). It assumes
the average outstanding balance over the plan is approximately
P × (n+1) / (2n) and charges the whole finance charge on that
average balance for n/12 years. It is NOT an internal rate of
return (IRR): it never discounts individual installments, so it does
not solve for the rate that makes the present value of the payments
equal the financed principal.

(b) Payment schedule implied. Down payment at t=0, then n equal
installments at the end of each month (t=1..n), no other payments.
No fees are included: fees are not an input to
`audit_installment_plan` or to the installment-audit endpoint at all,
so the calculation contains no fee, processing charge, insurance, or
late-payment amount of any kind. If a real plan charges fees, both
figures understate its true cost.

(c) Nominal vs effective vs approximation. The constant-ratio result
is neither a nominal APR compounded monthly (12 × monthly rate) nor
an effective annual rate ((1 + monthly rate)^12 − 1). It is a
closed-form approximation that overstates the rate badly when the
finance charge is large relative to the principal — exactly the
documented example, where the finance charge (77,000) is 53.1% of the
financed principal (145,000). That is why it reads ~98% while the
test plan expected ~42%: the two numbers are answers to different
questions, and the approximation is the one that is far from either
standard rate for these inputs.

(d) Why 42% cannot be reproduced. The cash-flow IRR on the exact
documented inputs (cash 165,000, down 20,000, 18,500 × 12,
end-of-month installments) was solved by bisection on
NPV(r) = 145,000 − Σ 18,500/(1+r)^t, t=1..12, NPV=0:
monthly rate 7.2502%, nominal APR compounded monthly 87.00%,
effective annual rate 131.62% (NPV at the solved rate ≈ 0 to within
1e-6). Checked variants do not yield ~42% either: installments at
the beginning of each month (annuity-due) give 178.15% effective;
ignoring the down payment (financing the full 165,000) gives 77.32%
effective. At a 42% effective rate the monthly rate would be 2.965%
and the present value of the 12 installments would be 184,532 —
greater than the 145,000 financed, so NPV cannot be zero. A 42%
effective rate would require a monthly installment of ≈14,537
(total paid ≈194,442, finance charge ≈29,442), not the actual
18,500 / 77,000. No standard cash-flow IRR on these exact inputs
yields ~42%; the test plan's figure does not follow from its own
formula or from the cash flows, and no output was forced to 42%.

Resolution adopted (Part 2): `InstallmentAudit` keeps `apr_percent`
as the legacy constant-ratio figure with its existing meaning, and
gains `effective_annual_rate_percent` (the cash-flow IRR, expressed
as an effective annual rate) and `apr_method` (which method produced
the effective figure, or the fallback label). The installment-markup
rule in the analyzer keeps using `markup_percent` (>35% → Risky
floor) and does not switch to either rate. The frontend needs no
change: `ToolsPanel` renders every field the backend returns
generically, so the two new fields display automatically.

## Ollama live-test status (Reliability Hardening — Part 2, 2026-11-03)

Ollama NOT tested live — no daemon reachable at 127.0.0.1:11434 in this environment

## Reliability Hardening — Parts 1 and 3 resolutions (recorded 2026-11-03, Part 4)

Appended, not a rewrite: the APR resolution above stays intact.
Evidence quality (Part 1): a verdict's evidence is "verified"
only for a live scrape with at least 5 usable samples from at
least 2 sources; "limited" for a live scrape with 3–4 usable
samples or 1 source, or a fresh baseline; "insufficient" for an
asking-price-only estimate, a baseline older than 90 days, or a
live attempt that fell back with fewer than 3 usable samples.
Insufficient evidence forces Low confidence, limited caps High
to Medium when sample detail was supplied, and a band derived
only from the asking price (or a stale baseline) can never
independently justify Great Buy. Live samples are deduped
(same rounded price + same normalized source), currency-mismatched
samples are dropped, and outliers are trimmed by the IQR rule
only with 5+ surviving samples; baselines are used only when
currency and unit match the request. Security (Part 3): the
title-injection gap was real and fixed — `analyze` now scans the
sanitized full title together with description and seller notes,
because the title reaches the Ollama payload; deletion orphans
were real and fixed — deleting a check now explicitly deletes
its chat messages/threads, journal rows, watchlist rows and
project associations before the row itself, instead of a bulk
delete bypassing ORM cascades; rate limiting (30/min per IP,
`app/rate_limit.py`) now covers POST /analyze, /analyze/stream,
chat messages, all 8 tools, image upload and watchlist
create/recheck, while GET endpoints are not limited. Perishables
(Part 3): `transit_damage_percent` (0–0.9 fraction) is an additive
request override for the hardcoded 10% transit damage, wired
through `analyzer.py` into `build_cash_flow` (absent means the
10% default); spoilage now carries an `assumptions` list naming
every value actually assumed (selling price, temperature,
transit damage) plus the statement that profit figures are
projections, not guaranteed, and the frontend renders it.
