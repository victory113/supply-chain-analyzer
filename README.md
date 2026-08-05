# AI Supply Chain Intelligence Platform

Upload supply chain CSVs, get computed risk analytics and AI-generated explanations, and track how performance changes over time.

### ▶ [Try it live](https://supply-chain-analyzer.netlify.app/) · [API docs](https://sca-api-o5p5.onrender.com/docs)

Create an account with any email, click **Try sample data**, and the dashboard fills in immediately. The AI risk assessment follows a few seconds later — that gap is the architecture, not lag.

Bringing your own file? Any shipment or order CSV up to 100 MB works, without renaming a single column — [**what files can I upload?**](./DATA.md)

> **First load takes 30–60 seconds.** The API runs on a free tier that sleeps when idle; it wakes on the first request. Reload if it errors once.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?style=flat&logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat&logo=postgresql&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=flat&logo=celery&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)
![Claude API](https://img.shields.io/badge/Anthropic-Claude_API-D4A27F?style=flat)

![Dashboard — computed KPIs, composite risk score with its weighted drivers, and the monthly delay trend](./screenshot.png)

---

## The core design decision

**Every number in this product is computed in Python. Claude never calculates anything.**

The analytics engine (`app/services/analytics/`) is pure, dependency-free stdlib code: KPIs, vendor health scores, country risk, delay trends, and a weighted composite risk score. Given the same rows it always produces the same numbers.

Claude receives that finished report as a *metrics brief* and is asked to explain it — with a system prompt that forbids computing figures and requires each risk to name the specific metric field it rests on (`evidence_metric`). That's what makes recommendations traceable.

Three consequences that fall out of the split:

- **The dashboard survives an LLM outage.** If the Claude call fails, the deterministic metrics are already persisted and every `/analytics` endpoint keeps working. There's a test for exactly this (`test_model_failure_keeps_the_computed_metrics`).
- **Results are reproducible.** A risk score can be recomputed and audited; a model's opinion cannot.
- **Cost scales with datasets, not rows.** The model sees an aggregate brief, never 50,000 raw shipment rows.

---

## Architecture

```
React + Netlify  ─────────────► FastAPI (JWT auth)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              PostgreSQL       Claude API      Celery + Redis
              (SQLAlchemy       (narration)     (background jobs
               + Alembic)                        + response cache)
                    │
                    ▼
            Analytics engine  ← pure Python, no I/O
```

### Request flow

```
POST /uploads  →  parse + validate CSV      (synchronous, ~50ms)
               →  persist shipments          (synchronous)
               →  queue analysis job         → 202 Accepted + poll_url
                        │
       Celery worker ───┤
                        ├─ compute analytics       (deterministic, always runs)
                        ├─ persist metrics + score  ← written BEFORE the AI call
                        ├─ call Claude for narration
                        └─ persist risks + summary
```

The upload returns `202` in under a second; the model call happens off the request path. The client polls `GET /analyses/{id}/status` — a deliberately tiny payload.

---

## Backend layout

```
backend/app/
├── api/v1/          Routes — the only layer that knows about HTTP
│   ├── auth.py      register / login / me
│   ├── uploads.py   ingest CSV, list, delete, sample data
│   ├── analyses.py  poll status, read results, re-run, compare
│   ├── analytics.py computed metrics (no AI call on any of these)
│   ├── chat.py      retrieval-grounded Q&A
│   └── health.py    liveness + readiness probes
├── services/        Business logic
│   ├── analytics/   THE deterministic engine (kpis, vendors, countries,
│   │                trends, risk, stats) — pure functions, no I/O
│   ├── csv_ingest.py   column mapping, coercion, validation
│   ├── analysis.py     ingestion + AI orchestration
│   ├── chat.py         retrieval + intent routing
│   ├── claude.py       the only file that touches the Anthropic SDK
│   ├── prompts.py      prompt construction (unit-testable, no network)
│   └── auth.py         registration, login, token issuance
├── repositories/    All SQLAlchemy queries live here, nowhere else
├── models/          SQLAlchemy ORM models
├── schemas/         Pydantic request/response contracts
├── workers/         Celery app + tasks
├── core/            config, security, logging, exception taxonomy
├── db/              engine, session, declarative base
└── middleware.py    request IDs, access logs, timing
```

The dependency direction is strictly one-way: `api → services → repositories → models`. Services never import from `api`; the analytics engine imports nothing but stdlib and its own schemas.

---

## Data model

| Table | Purpose |
|---|---|
| `users` | Accounts. bcrypt password hashes, never plaintext. |
| `uploads` | One CSV ingestion event: filename, row counts, status, error. |
| `shipments` | Normalised rows. Composite indexes on `(upload_id, vendor)` and `(upload_id, origin_country)`. |
| `analyses` | One AI run: status, summary, risk score, token usage, and a `metrics_snapshot` of everything that grounded it. |
| `risks` | Individual findings, each with an `evidence_metric` pointing back at the computed field it cites. |

`ON DELETE CASCADE` throughout, so deleting an upload takes its shipments, analyses, and risks with it.

---

## API surface

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Returns a token immediately |
| `POST` | `/api/v1/auth/login` | Timing-equalised — identical error and latency for unknown email vs. wrong password |
| `GET` | `/api/v1/auth/me` | |
| `POST` | `/api/v1/uploads` | multipart CSV → `202` + `poll_url` |
| `GET` | `/api/v1/uploads` | Paginated |
| `GET` | `/api/v1/uploads/{id}/shipments` | Paginated rows |
| `DELETE` | `/api/v1/uploads/{id}` | |
| `GET` | `/api/v1/uploads/{id}/analysis` | Latest analysis for an upload |
| `GET` | `/api/v1/uploads/sample` | Sample CSV, no auth needed |
| `GET` | `/api/v1/analyses/{id}/status` | Small polling payload |
| `GET` | `/api/v1/analyses/{id}` | Full result incl. metrics snapshot |
| `POST` | `/api/v1/analyses/{id}/rerun` | |
| `POST` | `/api/v1/analyses/compare` | Before/after diff of two uploads |
| `GET` | `/api/v1/analytics/uploads/{id}` | **No AI call** — full computed report |
| `GET` | `/api/v1/analytics/uploads/{id}/{kpis,vendors,countries,trend,risk}` | **No AI call** |
| `GET` | `/api/v1/analytics/history` | Cross-upload trend |
| `POST` | `/api/v1/chat` | Grounded Q&A with cited sources |
| `GET` | `/api/v1/health`, `/health/ready` | Liveness / readiness |

Interactive docs at `/docs` once running.

Every upload, analysis, and analytics read is scoped to the authenticated owner at the query level (`get_for_user`, not `get`), so an authenticated user cannot reach another tenant's data by guessing an ID. There's a test for that too.

---

## The analytics engine

### KPIs
Total and late shipments, late %, mean/median/p90 delay, mean delay *when late*, average lead time, delivery success rate, total value, value at risk, distinct vendors and countries.

Two details worth calling out: p90 is reported alongside the mean because tail risk is what actually breaks a supply chain, and lead-time averages skip rows with no lead time rather than averaging in zeros.

### Vendor health (0–100)
```
50% punctuality  +  30% delay severity  +  20% lead-time reliability
```
Punctuality is weighted highest because a vendor that is *reliably* slow is easier to plan around than one that is unpredictably late. Delays are capped at 21 days before scoring, so one 400-day outlier can't flatten the range. Vendors with fewer than 2 shipments are excluded from the ranking — a single late delivery would otherwise read as 100% failure.

### Country risk (0–100)
```
60% late rate  +  40% delay severity
```
Observed, not geopolitical — derived only from how that origin has actually performed in the user's data, so the number is always explainable from the uploaded file.

### Composite risk (0–100)
```
30% late rate  +  25% delay severity  +  20% value at risk
              +  15% vendor concentration  +  10% country concentration
```
Concentration is a Herfindahl index over spend share: 1.0 means a single supplier carries everything. The API returns the score, its components, *and* the weights, so the dashboard can explain why a number moved, and `describe_drivers()` ranks drivers by contribution (component × weight) rather than raw value.

### Trends
Monthly buckets, with direction called by comparing the first half of the series against the second — more robust than first-vs-last point. Fewer than 3 dated periods returns `insufficient_data` rather than inventing a trend.

---

## Running it

### Docker (everything)

```bash
docker compose up --build
```

Brings up Postgres, Redis, the migration job, the API, and the Celery worker. API on `http://localhost:8000`, docs at `/docs`. Set `ANTHROPIC_API_KEY` in your environment first; without it the deterministic analytics still work and only the AI narration fails.

### Local, with nothing else installed

No Postgres, no Redis, no Docker — just Python and Node:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                  # then fill in ANTHROPIC_API_KEY

DATABASE_URL=sqlite+aiosqlite:///./dev.db uvicorn app.main:app --reload
```

On a SQLite DSN the app creates its tables at startup and skips Alembic; on
anything else that bootstrap refuses to run, so Postgres schemas stay
migration-managed. With no Redis, the cache no-ops and the analysis runs as an
in-process background task instead of on a worker — the API response shape is
identical either way. See `app/db/init_db.py` and `app/workers/broker.py`.

### Local, against Postgres

```bash
cd backend
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

In a second terminal:

```bash
cd backend
celery -A app.workers.celery_app worker --loglevel=info -Q analysis
```

Without a worker the API falls back to running analyses in-process via `BackgroundTasks`, so local development works with no broker — the response shape is identical either way.

A `Makefile` wraps the common commands (`make dev`, `make test`, `make lint`, `make migrate`).

---

## Tests

```bash
cd backend
pytest --cov=app
```

161 tests, all passing, in about 20 seconds.

| Suite | Covers |
|---|---|
| `tests/unit/test_analytics.py` | Every metric and scoring rule — the numbers the product reports |
| `tests/unit/test_csv_ingest.py` | Header aliasing, type coercion, encodings, row rejection |
| `tests/unit/test_security_and_prompts.py` | bcrypt, JWT expiry/tampering, prompt grounding, chat intent routing |
| `tests/unit/test_cache_and_broker.py` | Cache circuit breaker, Redis degradation, broker probe |
| `tests/unit/test_enqueue_fallback.py` | Job enqueue falls back in-process when the broker is down |
| `tests/db/test_init_db.py` | Local-dev schema bootstrap, and its refusal to run on Postgres |
| `tests/api/test_auth_api.py` | Registration, login, token handling, health probes |
| `tests/api/test_uploads_api.py` | Upload flow, pagination, **tenant isolation**, analytics endpoints |
| `tests/db/test_repositories.py` | Query scoping, pagination, cascades |
| `tests/db/test_analysis_service.py` | Full pipeline with Claude stubbed, incl. LLM-failure degradation |

The suite runs on in-memory SQLite (the `GUID`/`JSON` column variants in `app/db/base.py` make the same models work on both engines), so it needs no services and finishes in seconds. CI additionally applies the migrations against real Postgres — `upgrade → downgrade → upgrade` — so schema changes are validated where they'll actually run.

---

## CI/CD

`.github/workflows/ci.yml` runs on every push and PR:

1. **Backend lint** — `ruff check` + `ruff format --check`, and `mypy` (visible but non-blocking while annotations are tightened)
2. **Backend tests** — full suite with coverage, then the Postgres migration round-trip
3. **Frontend** — ESLint, `tsc --noEmit`, Vitest, and a production build
4. **Docker** — build the image and smoke-test that it serves `/api/v1/health`

---

## Engineering notes

A few decisions that took more thought than the code suggests:

**Async everywhere, including the worker.** Celery is synchronous but the data layer is async. Rather than maintaining a parallel sync stack, each task drives the existing async code with `asyncio.run` — and builds a *fresh* engine inside that loop, because asyncpg connections are bound to the loop that created them. Reusing the module-level engine produces "attached to a different loop" failures that only appear under concurrency.

**Errors are a taxonomy, not status codes.** Services raise `NotFoundError`, `ConflictError`, `UpstreamServiceError`; only `app/core/exceptions.py` maps those to HTTP. Inner layers stay transport-agnostic, and every error response shares one envelope.

**The cache can always be down — and must be cheap when it is.** Every Redis operation degrades to "no cache", but *degrading gracefully is not the same as degrading cheaply*. Running the app without Redis showed redis-py retrying each refused connection internally, so a page issuing a get and a set paid ~8 seconds. A circuit breaker now opens after three consecutive failures and short-circuits for 30 seconds. It also cut the test suite from 146s to 22s.

**Celery cannot be made to fail fast on publish.** Same session, worse symptom: with the broker down, uploads hung indefinitely. `retry=False` on `apply_async` disables *publish* retry, but kombu still runs its own connection loop (100 attempts by default), and turning that off globally would stop a live worker from reconnecting. So the API TCP-probes the broker itself before publishing and goes straight to the in-process fallback when nothing answers. Uploads went from hanging to 202-in-1.4s.

**Ingestion is forgiving about cells, strict about rows.** Real exports are inconsistent, so columns are matched by alias (`"Unit Cost"`, `"unit_cost"`, `"unitprice"` all resolve), the delimiter is sniffed (`, ; tab |`), encodings fall back through UTF-8-BOM → cp1252, and an unparseable cell becomes null. A row is rejected only when *every* recognised column is empty — an earlier rule demanded a vendor, reference or product specifically, and silently threw away entire public datasets whose identity column happened to be named something else. Rejection counts are surfaced, not hidden.

**The most important column is usually the one that isn't there.** Almost no real export carries `delay_days`; it carries a promised date and an actual date and expects you to subtract. Without that derivation every shipment reads as on-time, the risk score comes out zero, and the dashboard looks *confidently* wrong — the worst failure mode available. Ingestion now derives delay from any scheduled/actual pair across 18 date formats, infers status from the derived delay, and dates each row from `shipped → actual → scheduled` so the trend chart has periods to plot. The count of derived values is reported back to the user, because a number the app invented should not be indistinguishable from one the file supplied.

**100 MB uploads are a memory-shape problem, not a limit change.** Raising the cap meant nothing while the parser built one list of ORM objects for the whole file. Rows are now yielded in batches of 5,000; each batch is flushed and expunged from the identity map, so peak memory tracks the batch, not the file. (Expunging the *whole* session was the obvious version and was wrong — it detaches the `Upload` too, and the row counts written afterwards vanish without an error.)

**Then it was a speed problem, and the cost was in an exception handler.** 300,000 rows took 84 seconds. The culprit was date parsing: matching one of 18 formats means raising and catching a `ValueError` for every format ahead of the right one, twice per row — about 3M exceptions. But a year of shipments contains only a few hundred *distinct* date strings, so an `lru_cache` on the format search collapses those 3M attempts to a few hundred. Same 300,000 rows: **14 seconds**. Worth knowing where the time actually was before optimising anything structural.

**Chat retrieval is keyword-routed, not vector-based.** For a fixed, small set of metric families, routing a question to the relevant slices is cheaper and more predictable than embedding search — and the answer cites which slices it used.

---

## Frontend

React 18 + TypeScript on Vite, with TanStack Query for server state and Recharts for visualisation. Deployed to Netlify.

```
frontend/src/
├── api/           Typed client — the only place that knows about HTTP
│   ├── client.ts    fetch wrapper, token storage, error envelope → ApiError
│   ├── endpoints.ts one function per route + centralised query keys
│   └── types.ts     mirrors the backend's Pydantic schemas field for field
├── auth/          AuthContext, useAuth, ProtectedRoute
├── components/
│   ├── charts/      RiskGauge, DelayTrendChart, VendorHealthChart,
│   │                CountryExposure, HistoryChart, shared dark tooltip
│   ├── ui/          Card, Badge, Field, Spinner, loading/empty/error states
│   ├── KpiGrid, RiskList, UploadDropzone, AnalysisProgress, Layout
├── hooks/         useAnalysisStatus — polls a queued analysis to completion
├── lib/format.ts  All display formatting, unit-tested
└── pages/         Login, Register, Dashboard, Uploads, UploadDetail,
                   History, Compare, Chat
```

**Screens**

| Route | What it does |
|---|---|
| `/login`, `/register` | JWT auth; the token is verified against `/auth/me` before a session is restored |
| `/` | Latest dataset at a glance — KPIs, risk gauge, delay trend, worst vendors, geographic exposure |
| `/uploads` | Drag-and-drop upload, paginated history, delete |
| `/uploads/:id` | Full report: KPIs, risk breakdown, trend, vendor chart + table, AI risks |
| `/history` | Risk score and late rate across every analysed dataset |
| `/compare` | Before/after diff with a metric-by-metric table and AI commentary |
| `/chat` | Grounded Q&A, scoped to one dataset or across history, with cited sources |

**Three decisions worth explaining**

*Polling, not waiting.* Upload returns `202` and the model call happens in a worker, so `useAnalysisStatus` polls a small status payload and stops the moment the analysis reaches a terminal state. There's a poll budget, so a wedged job surfaces as a timeout rather than an infinite spinner.

*The AI failing is not the page failing.* Because the analytics endpoints never call the model, a failed analysis renders a warning banner that explicitly says the metrics below are unaffected — and they are, because the backend persists them before the model call.

*Every risk shows its evidence.* `RiskList` renders the `evidence_metric` the model was required to cite. There's a test asserting it stays visible; without that link a recommendation is an unverifiable claim.

**Geographic view.** "Geographic exposure" is a ranked panel (volume share, risk score, delay per origin) rather than a choropleth. A world map needs a vendored topojson of ~100KB and renders mostly empty ocean for a dataset covering 3–10 origins. The panel carries the same three facts per country and stays readable at any size — a real map is on the roadmap if the data ever justifies it.

### Running the frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The dev server proxies `/api` to `http://localhost:8000`, so the frontend uses the same relative URLs in development and production and never triggers CORS locally. In production the Netlify redirect in `netlify.toml` does the same job, forwarding to the deployed Render service.

```bash
npm run test         # Vitest + Testing Library
npm run typecheck    # tsc --noEmit, strict mode
npm run lint         # ESLint (typescript-eslint + react-hooks)
npm run build        # type-check then production bundle
```

Tests cover the API client (auth headers, error-envelope unwrapping, 401 token clearing, network failures, multipart headers), the formatters — including that `levelFromScore` matches the backend's `RiskLevel.from_score` thresholds exactly — and component behaviour for `RiskList` and `UploadDropzone`.

The original single-file v1 UI is preserved at [legacy/v1-single-file-ui.html](legacy/v1-single-file-ui.html). It predates authentication and targets the old unversioned endpoints, so it does not work against this API.

---

## Roadmap

- [x] Layered FastAPI architecture with SQLAlchemy, Alembic, Postgres
- [x] JWT authentication and per-tenant data scoping
- [x] Deterministic analytics engine — KPIs, vendor scores, country risk, trends, composite risk
- [x] Persisted uploads, shipments, analyses, and risks
- [x] Asynchronous processing with Celery + Redis
- [x] Redis response caching
- [x] Retrieval-grounded AI chat over stored data
- [x] Structured logging, health/readiness probes, request tracing
- [x] Docker Compose, GitHub Actions CI, Render blueprint
- [x] React + TypeScript dashboard — charts, upload history, compare, AI chat
- [ ] True choropleth map (needs a vendored world topojson)
- [ ] PDF report export
- [ ] Rate limiting and API keys for programmatic access

---

## Author

**Victory Orobosa** — CS Senior @ University of Central Arkansas

[Live demo](https://supply-chain-analyzer.netlify.app/) · [Source](https://github.com/victory113/supply-chain-analyzer) · [API docs](https://sca-api-o5p5.onrender.com/docs)

Frontend on Netlify · API and worker on Render · Postgres on Neon
