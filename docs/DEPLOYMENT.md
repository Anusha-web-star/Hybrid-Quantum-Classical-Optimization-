# Deploying GRIDOPT on Render

What runs where, what to set, and — the part that matters most — what cannot run
on Render at all.

The local setup is unchanged. Everything here is additive: `render.yaml`, four
pinned dependencies that were previously a comment, and one environment-driven
CORS list. No solver, no QAOA code, no dataset, no retrieval logic and no UI
component was modified.

## Architecture

```
          browser
             │
             │  1. static files (HTML/JS/CSS)
             ▼
  ┌──────────────────────────┐
  │  gridopt-dashboard       │   Render Static Site  (free)
  │  Vite build of frontend/ │   built: npm ci && npm run build
  └──────────────────────────┘   served from frontend/dist
             │
             │  2. XHR to VITE_API_BASE, cross-origin
             │     Authorization: Bearer <supabase jwt>
             ▼
  ┌──────────────────────────┐
  │  gridopt-api             │   Render Web Service  (standard: 1 CPU / 2 GB)
  │  FastAPI + Phase 1/2     │   uvicorn app.main:app --app-dir backend
  │  Aer simulator           │   health check: /health
  └──────────────────────────┘
          │            │
          │            └── 4. BM25 retrieval over outputs/assistant_index.json
          │                   (in-process, committed to the repo — works here)
          │
          │  3. verify JWT against public JWKS; read network tables
          ▼
  ┌──────────────────────────┐
  │  Supabase (unchanged)    │   stays where it is — not moved to Render
  │  Auth + Postgres         │
  └──────────────────────────┘

  ✗ Ollama + llama3.2:3b     NOT deployable here. See "The RAG assistant" below.
  ✗ IBM Quantum hardware     not installed, not configured, not reachable.
```

Three origins, one of which is not ours: the dashboard, the API, and Supabase.
That is why CORS has to be configured at all — see below.

## 1. Backend (FastAPI)

A Render **web service**, `runtime: python`, built from the repository root:

```
buildCommand: pip install --upgrade pip && pip install -r backend/requirements.txt
startCommand: uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT --workers 1 --timeout-keep-alive 120
```

Three things make this work without restructuring the project:

- **`--app-dir backend`** is the same flag the local command uses, so the
  deployed process starts the identical application.
- **`backend/app/__init__.py`** already puts the repository root on `sys.path`,
  so `phase1` and `phase2` import from where they live. The solvers are used as
  they are; nothing was copied into the backend package.
- **`--host 0.0.0.0 --port $PORT`** is Render's requirement. `API_HOST`/`API_PORT`
  in settings are for the local CLI and are untouched.

**One worker, on purpose.** A hybrid run is CPU-bound. On a 1-CPU plan a second
worker would make two concurrent runs slower than letting them queue, while
doubling the memory floor.

**Health check** is `/health`, which was already open (unauthenticated) because
the dashboard polls it for its connection indicator before a session exists.
Render needs exactly that: no credential, 200, cheap. Nothing had to change.

**Measured footprint** (this project, local, Python 3.13.7): 229 MB RSS for the
app import plus a hybrid run. That fits a 512 MB plan; the reason to pick
`standard` is CPU, not memory.

### Ephemeral disk

`POST /solve/compare` writes three PNGs into `outputs/`. Render's filesystem is
ephemeral, so those are lost on every deploy and restart. This is harmless here:
the committed copies are present at boot, and `/solve/compare` regenerates them
on demand. Do not add a persistent disk for this — it would buy nothing.

## 2. Frontend (React / Vite)

A Render **static site**, `rootDir: frontend`, `npm ci && npm run build`,
published from `./dist`. Free, on a CDN, no server process.

**No frontend source change was needed.** `frontend/src/api/client.js` already
reads `VITE_API_BASE` and `apiUrl()` already routes graph `<img>` sources through
it, so there was no localhost URL hard-coded anywhere to remove.

`VITE_API_BASE` **must** be set on the static site — it is the one variable that
is optional locally and mandatory deployed. Empty, the bundle asks its own origin
for `/health`, where nothing is listening, and the dashboard shows a dead
backend. Set it to the API's URL with no trailing slash.

Locally, leave it empty: the Vite dev proxy in `vite.config.js` keeps the browser
on one origin, which is why local development needs no CORS configuration at all.

## 3. Supabase

**Stays exactly where it is.** It is already a hosted service; moving it to a
Render Postgres instance would mean migrating Auth, re-issuing every user, and
rewriting `frontend/src/lib/supabase.js`. None of that is deployment work.

Set on the **backend** service:

| Variable | Secret? | Why |
| --- | --- | --- |
| `SUPABASE_URL` | public | locates the project's public JWKS; checks a token's issuer |
| `SUPABASE_SERVICE_ROLE_KEY` | **secret** | direct Data-API access to the network tables; bypasses RLS |
| `AUTH_MODE=supabase` | — | verify every token's signature before any handler runs |

Set on the **static site**:

| Variable | Secret? | Why |
| --- | --- | --- |
| `VITE_SUPABASE_URL` | public | |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | public by design | identifies the project, carries no authority; RLS decides access |

Two rules that the code already enforces and Render must not be used to break:

1. **The service-role key never goes on the static site.** Everything
   `VITE_`-prefixed is compiled into a public JavaScript file.
   `frontend/src/lib/supabase.js` throws at startup if a secret key appears in
   the public slot — but do not rely on that; just never set it there.
2. **`AUTH_MODE=demo` must not be set on a deployed service.** It admits every
   request with no credential. It exists for running the API with no Supabase
   project reachable. It is not a security boundary.

Verification needs no secret: the project signs with ES256, so the backend checks
signatures against Supabase's *public* keys. The service-role key is not used for
auth and never has been.

## 4. The RAG assistant — cannot run on Render

**Read this before deploying.** Nothing about the assistant was changed, removed
or swapped. Here is why it cannot be hosted, in its current form, on Render.

`backend/app/assistant/llm.py` sends generation to Ollama on loopback. Two hard
constraints follow:

| | Requirement | Render reality |
| --- | --- | --- |
| Memory | llama3.2:3b is ~2 GB on disk and needs ~2.5–3 GB resident, *on top of* the 229 MB the API already uses | free/starter = 512 MB; standard = 2 GB. Only `pro` (4 GB, $85/mo) could physically hold it |
| CPU | CPU-only inference; this project already allows 180 s (`ASSISTANT_TIMEOUT_S`) on a developer laptop | free = 0.1 CPU, standard = 1 CPU. Per-answer latency would run into minutes |
| Lifecycle | Ollama is a separate long-running server, not a Python package | would need a second process in the same container, plus a 2 GB model re-download on every cold start, since the disk is ephemeral |
| By design | `_endpoint()` **refuses any non-loopback `OLLAMA_HOST`**, so the project's data cannot be shipped to a remote model by a config change | a hosted Ollama elsewhere is therefore not a workaround — it is blocked on purpose |

**What was done instead: nothing.** The assistant ships deployed exactly as it is
written, and degrades the way its author already made it degrade:

- **Retrieval works.** BM25 runs in-process over `outputs/assistant_index.json`,
  which is committed, so `GET /assistant/status` reports a real knowledge base on
  the deployed API.
- **Generation answers `503 assistant_not_configured`**, carrying the existing
  message and the exact `ollama pull llama3.2:3b` command that fixes it. The
  panel already renders this state. The assistant is not silently missing, and it
  never invents an answer.
- **Locally it is fully functional and unchanged.**

If you want the assistant live, the options — none of which I have taken:

1. **Leave it local.** The deployed dashboard is the optimizer; the assistant is
   a local tool. Zero cost, zero change. This is what the current config does.
2. **Render `pro` (4 GB, $85/mo) with Ollama as a second process in the container.**
   Physically possible. Expect minutes per answer on 2 shared vCPUs and a 2 GB
   model pull on every cold start. I would not ship this.
3. **A GPU host for Ollama** (Render has no GPU plan for web services) reached
   over a tunnel that presents as loopback. This keeps `llm.py` untouched and
   honest, but it is real infrastructure.
4. **A hosted inference API.** Rejected — you asked not to replace Ollama, and
   it would send the GRIDOPT dataset off-machine, which is the specific thing
   `llm.py` is built to prevent.

Tell me which, if any, you want. Until then the deployed assistant reports its
own state truthfully and the local one keeps working.

## 5. Hybrid QAOA on Render

It runs, but it is the slowest thing in the system and the plan choice is
entirely about it.

**Measured here: 84.1 s** for `/solve/hybrid` at the committed defaults
(`window=4, sweeps=8, shots=2048, maxiter=20`) on this developer machine.

Render does not cut long requests off — HTTP responses may take far longer than
this — so the risk is not a timeout at the platform edge. The risk is CPU:

| Plan | CPU | Expected `/solve/hybrid` |
| --- | --- | --- |
| free | 0.1 | many minutes; also spins down after 15 min idle, and cold start pays the qiskit/pandas/matplotlib import |
| starter | 0.5 | roughly 3–5 minutes |
| **standard** | **1** | **closest to the 84 s measured locally** |

`render.yaml` therefore specifies `standard`, and sets two environment overrides
for the deployed service only:

```
QAOA_SWEEPS=4      # default is 8
QAOA_SHOTS=1024    # default is 2048
```

**This is configuration, not an algorithm change.** `Settings` already exposes
every QAOA knob as an environment variable, so this needed no code edit; the
committed defaults in `backend/app/core/config.py` are untouched, `run_phase2.py`
is untouched, and a request may still pass its own `sweeps`/`shots` to get the
full run. Delete both variables to deploy with the exact local defaults.

Memory is not a constraint: 16 qubits is a 1 MB statevector.

**On the free plan specifically**, also budget for cold starts. A free service
spins down after 15 minutes without traffic and takes about a minute to come
back — and this app's first import is qiskit, qiskit-aer, pandas and matplotlib,
so expect longer than that on the first request after idle.

### IBM Quantum

Not deployed, and not deployable by accident. `qiskit-ibm-runtime` is
deliberately **excluded** from `backend/requirements.txt`: `phase2/backends.py`
imports it lazily inside the IBM branch only, so leaving it out makes a hardware
job impossible rather than merely unconfigured. No IBM token is set on any Render
service. Every deployed run uses the local Aer simulator.

## 6. CORS

Deployed, the dashboard and the API are on different origins, so the browser
preflights every call. Locally they share an origin via the Vite proxy, so this
never comes up — which is exactly why it is easy to get wrong on the first deploy.

`CORS_ALLOWED_ORIGINS` on the backend is a comma-separated list. The two
localhost dev origins are **always** allowed by `Settings.cors_origins`, so local
development keeps working no matter what is set:

```
CORS_ALLOWED_ORIGINS=https://gridopt-dashboard.onrender.com
```

- **No trailing slash.** An `Origin` header never has one, so
  `https://app.onrender.com/` would match nothing. The setting strips it anyway;
  the tests in `backend/tests/test_health.py` pin that behaviour.
- **Never `*`.** The API sends `allow_credentials=True`, and every browser
  rejects a wildcard alongside credentials.
- Render assigns the static site's URL when it is first created, so this is set
  *after* the first deploy of the frontend. Expect to set it, then redeploy — or
  rather, just restart the API; no rebuild is needed for an env var.

## Deploy order

Chicken-and-egg: each service needs the other's URL. One pass:

1. Push the branch. **Confirm `.env` is not in it** — it is git-ignored, and
   `git check-ignore .env` should print `.env`.
2. Render dashboard → **Blueprints** → New Blueprint Instance → pick this repo.
   It reads `render.yaml` and prompts for every `sync: false` value.
3. Fill in the Supabase values. Put placeholders in `VITE_API_BASE` and
   `CORS_ALLOWED_ORIGINS` for now.
4. Let both deploy. Note the two assigned URLs.
5. Set `VITE_API_BASE` to the API's URL on the static site → it rebuilds
   (`VITE_` values are baked in at build time, so a rebuild is required here).
6. Set `CORS_ALLOWED_ORIGINS` to the dashboard's URL on the API → restart.
7. In Supabase → Authentication → URL Configuration, add the dashboard's URL to
   **Site URL / Redirect URLs**, or email confirmation links will point at
   localhost.

## Verify

```bash
curl https://<api>.onrender.com/health          # {"status":"ok",...}
curl https://<api>.onrender.com/dataset/status  # found: true, 26 stations
curl https://<api>.onrender.com/assistant/status  # knowledge base present, no model
```

Then open the dashboard: the connection indicator should be live, the network map
should draw, `/solve/classical` should answer in milliseconds, and the assistant
panel should report that no local model is available — which is the correct and
expected state.

## Not hosted on Render

| | Why |
| --- | --- |
| Ollama + llama3.2:3b | §4 — memory, CPU, ephemeral disk, and a deliberate loopback-only guard |
| IBM Quantum hardware | out of scope by request; the package is not even installed |
| Supabase Auth / Postgres | already hosted; moving it is a migration, not a deployment |
| `frontend/reference/` (15 MB of .mp4) | tracked in git but outside the build — dead weight in clone and build time. Untouched; your call whether to remove it |
| `backend - Copy/` | a stray tracked directory (two files). Untouched; probably wants deleting |
