# Runbook

How to launch this app, demo it, and answer questions about it.

**Two things to remember before anything else:**

1. **Two terminals, and both stay open.** Terminal 1 runs the backend (the
   brain, port 8000). Terminal 2 runs the frontend (the screen, port 5173).
   Close either one and the app stops working.
2. **You visit `localhost:5173`, not `8000`.** 5173 is the website. 8000 is the
   API it talks to behind the scenes.

---

## 0. Start here — step by step

### Step 1. Open the project in VS Code

**File → Open Folder** →
`C:\Users\Owner\Documents\OneDrive\personal project\supply-chain-analyzer\supply-chain-analyzer`

*You should see:* a file tree with `backend`, `frontend`, `README.md`, `RUNBOOK.md`.

### Step 2. Open a terminal

Press `` Ctrl + ` `` (Control + backtick, the key above Tab).

*You should see:* a panel at the bottom with a prompt ending in `>`.

### Step 3. Start the backend

Paste this whole line and press Enter:

```powershell
cd "C:\Users\Owner\Documents\OneDrive\personal project\supply-chain-analyzer\supply-chain-analyzer\backend"; $env:DATABASE_URL="sqlite+aiosqlite:///./dev.db"; .venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

*You should see:*

```
schema_bootstrap_complete   dsn_kind=sqlite tables=5
INFO:  Application startup complete.
INFO:  Uvicorn running on http://127.0.0.1:8000
```

Leave this terminal alone from now on. It will look frozen — that is correct.
The server is sitting there waiting for requests.

### Step 4. Open a second terminal

Click the `+` icon at the top-right of the terminal panel (or the split-pane
icon next to it).

*You should see:* a second, empty prompt. The backend keeps running in the first.

### Step 5. Start the frontend

Paste this into the **new** terminal and press Enter:

```powershell
cd "C:\Users\Owner\Documents\OneDrive\personal project\supply-chain-analyzer\supply-chain-analyzer\frontend"; npm run dev
```

*You should see:*

```
VITE v6.4.3  ready in 993 ms
➜  Local:   http://localhost:5173/
```

### Step 6. Open the app

Browser → **http://localhost:5173**

*You should see:* a dark "Sign in" page.

### Step 7. Use it

1. Click **Create one** at the bottom.
2. Email: anything (`me@test.com`). Password: `test-pass-2026` — needs 8+
   characters and can't be only letters.
3. **Create account** → you land on the dashboard.
4. Click **Try sample data**.
5. Watch the order: charts and numbers appear **immediately**, the AI section
   fills in ~12 seconds later. That gap is the point of the whole design.

### Step 8. Stop it

Click into each terminal and press `Ctrl + C`. Do it in both.

### If something goes wrong

| You see | Do this |
|---|---|
| `ModuleNotFoundError` | Wrong folder. Re-paste the whole Step 3 line — the `cd` is part of it. |
| `'npm' is not recognized` | Close that terminal, open a fresh one, retry Step 5. |
| `address already in use` | A server is already running. Run `Get-Process python,node -ErrorAction SilentlyContinue \| Stop-Process -Force`, then retry. |
| "Could not reach the server" in the browser | Terminal 1 isn't running. Redo Step 3. |
| Page won't load at all | Terminal 2 isn't running. Redo Step 5. |
| Upload works but the AI section stays empty | No `ANTHROPIC_API_KEY` in `backend/.env`. Expected — every metric still works. |

---

## 1. Reference: what those commands actually do

Worth knowing so you can fix it live when something fails in front of someone.

| Line | Why it's there |
|---|---|
| `.venv\Scripts\python.exe` | Runs *this project's* Python, which has the packages installed. Using plain `python` gets you `ModuleNotFoundError: fastapi`. (`.venv\Scripts\activate` does the same thing for a whole session, but can trip PowerShell's execution policy — calling the exe directly avoids that.) |
| `$env:DATABASE_URL="sqlite+..."` | Overrides the Postgres default. On a SQLite DSN the app creates its own tables at startup and skips Alembic — see `app/db/init_db.py`. Everything else about the app is identical. |
| `uvicorn app.main:app` | `app.main` is the module, `app` is the FastAPI instance built by `create_app()`. `--reload` restarts on file save. |
| `npm run dev` | Vite dev server on 5173. It proxies `/api` → `localhost:8000` (`vite.config.ts`), which is why there's no CORS setup in development. |

You do **not** need Postgres, Redis, Docker, or a Celery worker for this. The
app detects each one is missing and degrades — that's deliberate, and it's
covered in §5.

---

## 2. The five-minute demo

**Before you start:** decide whether you want live AI. Every upload makes a
real Claude call (~1–2¢). Key lives in `backend/.env`. Remove it and the
dashboard still works fully — you just get a banner instead of the AI section.

1. **Register** — any email. Point out the password rule is enforced in *both*
   places: `RegisterPage.tsx` for instant feedback, `schemas/auth.py` because a
   client check is not a security control.

2. **Try sample data** — 12 shipments load.

3. **Watch the order things appear.** This is the whole point of the design:
   KPIs, risk gauge, trend, vendor chart and geographic panel render
   *immediately*; the AI risk assessment fills in ~10–15s later. Say why:
   > "The numbers are computed in Python. Claude only writes the explanation.
   > That's why the dashboard doesn't wait for the model — and why it still
   > works if the model is down."

4. **Scroll to an AI risk** and point at the grey line underneath:
   `grounded in vendors[0].health_score`. Every risk has to cite the computed
   field it rests on. That's the difference between a recommendation and a
   guess.

5. **Upload a second dataset**, then show **History** (risk score across
   uploads) and **Compare** (metric-by-metric diff, model only explains the
   delta).

6. **Ask AI** — "Which vendor should we replace first?" Point at the source
   chips under the answer: it names which stored metrics it used.

7. **http://localhost:8000/docs** — every endpoint, live. Good closer.

**Optional flex:** stop the backend mid-demo, reload the dashboard, show it
failing cleanly with a real error message rather than a blank screen or a
spinner that never resolves.

---

## 3. The one idea to be able to explain

> **Every number in the product is computed in Python. The model never
> calculates anything — it only explains numbers that already exist.**

Four consequences worth knowing cold:

1. **Reproducible.** Same CSV always gives the same risk score. You can
   recompute and audit it. A model's opinion you cannot.
2. **Survives an outage.** The backend persists the computed metrics *before*
   calling Claude (`services/analysis.py`, in `run_analysis`). If the call
   fails, the analysis is marked FAILED but every metric stands. There's a test
   named `test_model_failure_keeps_the_computed_metrics`.
3. **Traceable.** The prompt requires an `evidence_metric` per risk, so each
   claim points back at a specific field.
4. **Cheap.** The model sees an aggregate brief, never 50,000 raw rows.

---

## 4. Eight files worth knowing

Read these and you can hold a conversation about any part of it.

| File | What to say about it |
|---|---|
| `backend/app/services/analytics/risk.py` | The composite score: five weighted components. Returns its components *and* weights so the score is explainable. `describe_drivers()` ranks by contribution (component × weight), not raw value — a high component with a small weight isn't what's driving it. |
| `backend/app/services/analytics/vendors.py` | Vendor health = 50% punctuality, 30% delay severity, 20% lead time. Punctuality dominates because a *reliably* slow vendor is easier to plan around than an unpredictable one. Delays cap at 21 days so one outlier can't flatten the scale. |
| `backend/app/services/analysis.py` | The orchestration. Note the ordering in `run_analysis`: metrics persisted first, model called second. |
| `backend/app/services/csv_ingest.py` | Columns matched by alias, not exact name. Encoding falls back UTF-8-BOM → cp1252. A bad *cell* becomes null; a row is only rejected when it has no identity at all. Real exports are messy. |
| `backend/app/api/deps.py` + any repository | Ownership is enforced at the query level (`get_for_user`, not `get`), so a valid token for user A can't read user B's upload by guessing an ID. Test: `test_one_user_cannot_read_another_users_upload`. |
| `backend/app/workers/broker.py` | Why the API TCP-probes the broker instead of trusting Celery to fail fast. See §6 — this is your best story. |
| `backend/app/utils/cache.py` | Circuit breaker. Also §6. |
| `frontend/src/hooks/useAnalysisStatus.ts` | Upload returns 202 and polls a small status payload. Stops on a terminal state, with a poll budget so a stuck job surfaces as a timeout instead of an infinite spinner. |

---

## 5. What happens when things are missing

Worth knowing because someone will ask, and because it's why the app runs on
your laptop with no setup.

| Missing | What happens |
|---|---|
| **Postgres** | On a SQLite DSN, `init_db.py` creates the tables directly. It **refuses** to do this on any other database, so Postgres schemas stay Alembic-managed. |
| **Redis** | Cache no-ops. After 3 consecutive failures a circuit breaker opens for 30s so calls return instantly instead of retrying. |
| **Celery worker** | `broker.py` probes the broker; nothing listening means the analysis runs as a FastAPI `BackgroundTask` in-process. The API response shape is identical — the frontend can't tell. |
| **Anthropic key** | The analysis is marked FAILED with a clear message; every computed metric is untouched and the UI says so explicitly. |

---

## 6. Questions you'll get asked

**"Why not just let the LLM do the analysis?"**
Because you can't reproduce it, can't audit it, and it breaks when the API is
down. Also more expensive — the model would need every raw row. §3.

**"How do you handle a slow model call?"**
Upload returns 202 immediately after the rows are saved; the model call runs
in a worker. The client polls `/analyses/{id}/status`, a deliberately tiny
payload. Production uses Celery + Redis; locally it falls back in-process.

**"What was the hardest bug?"**
The honest and best answer — both were found by running the app without Redis,
not by reading the code:

1. **Uploads hung forever.** The fallback assumed `.delay()` would fail fast
   when the broker was down. It doesn't: `retry=False` disables *publish*
   retry, but kombu still runs its own connection loop (100 attempts by
   default). Turning that off globally would stop a live worker from
   reconnecting, so instead the API TCP-probes the broker before publishing.
   Hanging → 202 in 1.4s.

2. **"Degrades gracefully" wasn't degrading cheaply.** redis-py retries a
   refused connection internally, so a page doing a get and a set paid ~8
   seconds with Redis down. Added a circuit breaker. Side effect: the test
   suite went from 146s to 22s.

Both have regression tests (`tests/unit/test_enqueue_fallback.py`,
`tests/unit/test_cache_and_broker.py`).

**"Why SQLite locally and Postgres in production?"**
Dev/prod parity is a real cost here, paid deliberately. The models use column
variants (`GUID`, `JSON`/`JSONB`) so one definition works on both, the test
suite runs on SQLite in ~20s with no services, and CI additionally applies the
migrations to a real Postgres (`upgrade → downgrade → upgrade`) so schema
changes are validated where they'll actually run.

**"How do you know the analytics are right?"**
149 backend tests, and the ones that matter most pin the numbers — boundary
cases on every threshold, a vendor with delays past the cap not scoring
negative, single-vendor concentration maxing the Herfindahl index. The
frontend has a test asserting `levelFromScore` uses the *same* HIGH/MEDIUM/LOW
thresholds as the backend, so a chart and its badge can't disagree.

**"Why is there no map?"**
The geographic panel is a ranked exposure view, not a choropleth. A world map
needs a vendored ~100KB topojson and renders mostly empty ocean for the 3–10
origin countries a real dataset covers. Same three facts per country, readable
at any size. A real map is on the roadmap if data ever justifies it.

**"What would you do next?"**
Rate limiting and API keys for programmatic access; PDF export; and a real
choropleth. Longer term, the analytics engine is pure functions over
dataclasses, so moving the heavy aggregation into SQL for very large uploads
is a contained change — `ShipmentRepository.vendor_rollup` already does this
for vendors.

---

## 7. Proving it works, without clicking

```powershell
cd backend
.venv\Scripts\activate
pytest                    # 161 tests, ~20s
```

```powershell
cd frontend
npm run test              # 39 tests
npm run typecheck         # strict tsc, clean
npm run build             # production bundle
```
