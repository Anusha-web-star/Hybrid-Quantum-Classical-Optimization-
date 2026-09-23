# Hybrid Quantum-Classical Optimization for Energy Distribution (TSP)

Models Karnataka's power distribution network as a Travelling Salesman Problem and
compares a Classical solver against a Quantum (QAOA) solver.

**Status: Phase 2 — classical Nearest Neighbour plus a quantum QAOA solver.**
No frontend, database, authentication, or energy-loss logic yet.

## Phase 1 quick start

```bash
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install pandas matplotlib
```

```bash
.venv\Scripts\python.exe run_phase1.py --list
.venv\Scripts\python.exe run_phase1.py --start "Mysuru Substation"
.venv\Scripts\python.exe run_phase1.py            # prompts for a start station
```

Options: `--data PATH`, `--output PATH`, `--no-plot`, `--no-labels`,
`--component N` (route inside one connected group of a disconnected network),
`--layout {auto,geographic,force}`.

### Map readability

Five Kali river power houses (Kaiga, Kadra, Kodasalli, Nagjhari, Supa Dam) sit
within ~15 km of each other, so their markers would collapse onto one point at
grid scale. The map handles that without touching the data:

- stations are seeded at their **real CSV coordinates**, then an anchored
  repulsion pass pushes any overlapping markers apart while a decaying spring
  holds them near their true spot (max displacement on this dataset: **2.7% of
  the map span**);
- a hollow ring plus a hairline marks the **true coordinates** of every station
  that was nudged, so the map never misstates where a station is;
- station labels are placed by a collision-aware pass that avoids other markers,
  other labels, the leg-number badges and the axes edges, falling back to a
  leader line when a station is crowded;
- `--layout force` gives a force-directed view driven purely by the transmission
  lines — this is also the automatic fallback when the CSV has no coordinates.

No station is ever removed, merged or renamed, and no coordinate in the dataset
is modified.

The map is written to `outputs/nn_route.png`. Tests:

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Phase 2 quick start — one command

```bash
.venv\Scripts\python.exe -m pip install qiskit qiskit-aer qiskit-ibm-runtime
```

```bash
.venv\Scripts\python.exe run_phase2.py
```

That single command runs the complete Phase 2 comparison on the **full
26-station network**: it lists the stations and asks which to start from, solves
the network classically with Phase 1's Nearest Neighbour, solves it again with
the hybrid QAOA reoptimizer on the local simulator, validates both 26-station
tours, and writes three maps to `outputs/`. The terminal prints the results -
the two distances, execution times, stations visited, route validity, the
difference and the improvement percentage, the complete 26-station route each
solver travelled, and the map paths.

Pass `--start "Mysuru Substation"` to skip the prompt. It never touches IBM
hardware, and the whole workflow finishes in about 90 seconds.

| flag | effect |
|---|---|
| `--start NAME` | skip the interactive station prompt |
| `--window 5` | 25-qubit subproblems: shorter tour, but ~90 min to simulate |
| `--sweeps N` | cap on reoptimization sweeps (default 8; converges earlier) |
| `--no-labels`, `--layout` | map rendering, as in Phase 1 |
| `--verbose` | per-check validation, the comparison table, QAOA configuration and sweep progress |
| `--subset` | the separate single-instance QAOA mode (see below) |

### Full-network comparison — classical vs hybrid quantum

Both solvers get the **whole 26-station, 38-line network**, the same starting
station and the same `Distance_km` cost, and both return a complete tour that
starts at the chosen station, visits all 26 exactly once, and returns to it.

**How the hybrid works.** QAOA cannot take the whole network in one circuit —
the position-encoded QUBO would need (26−1)² = **625 qubits** and ~29,400 ZZ
couplings. Instead QAOA is the **optimization engine inside a classical
full-network reoptimization loop**: starting from the Phase 1 tour, a window of
`--window` consecutive stations is handed to QAOA as an open path-TSP
subproblem (`W²` qubits) with both endpoints pinned, and the new ordering is
kept when it shortens the tour. Every intermediate state is a complete
26-station tour.

**The QAOA windows are internal subproblems, never the answer.** A W=5 window is
a 5-station ordering problem inside the loop; the reported QAOA result always
contains all 26 stations. This is a hybrid decomposition/reoptimization
approach, and the project does not claim QAOA directly runs a 625-qubit
26-station TSP.

**What is not claimed.** No quantum advantage. For reference, unrestricted
classical 2-opt reaches 2,083.565 km on this network — better than the hybrid.
The limit is the window neighbourhood, not the quantum solver: at W=4 the hybrid
reaches *exactly* the tour an exhaustive brute-force subsolver finds over the
same windows, so QAOA is solving its subproblems optimally.

Maps written to `outputs/`: `nn_full_route.png`, `qaoa_full_route.png` and
`nn_vs_qaoa_comparison.png`. All three show all 26 stations and all 38 real
transmission lines, mark the starting station with a red star, number every leg
including the return, and use the same station coordinates (the layout is
deterministic) so the two routes are directly comparable.

### Single-instance QAOA mode (`--subset`)

```bash
.venv\Scripts\python.exe run_phase2.py --subset --start "Mysuru Substation"
.venv\Scripts\python.exe run_phase2.py --subset --mode ibm     # real hardware
```

Solves ONE small QAOA TSP end to end and compares it against Nearest Neighbour
and the exact optimum over the identical instance. This is the mode that runs on
IBM hardware. It is a **subproblem demonstration** — its route covers only
`--size` stations and is never the full-network result.

### Scope: the full network vs. the single-QAOA subset

**The project supports the complete dataset.** All **26 stations** and **38
transmission lines** in `data/` are loaded, validated and connected as one
network, and **Phase 1 solves that full network end to end** — every station
visited once, 3,017.795 km from `Mysuru Substation`. The CSV is never edited,
filtered, or reduced.

**Phase 2 runs QAOA on a subset of that same network, and only because of
quantum hardware limits.** The standard position-encoded TSP QUBO needs one
binary variable — and so one qubit — per (station, tour position) pair, which
grows as **O(n²)**. Pinning the start to position 0 leaves `(n-1)²` qubits:

| stations `n` | qubits `(n-1)²` | |
|---|---|---|
| 4 | 9 | fast demo |
| 5 | 16 | **Phase 2 default** |
| 6 | 25 | 33M-amplitude statevector |
| **26** | **625** | **the full network — not simulable, and beyond any device available today** |

So the subset is not a shortcut around the data; it is what current hardware can
carry. The `--size` stations are **selected directly from the real, complete
CSV** — the stations nearest the start by travel cost, or `--stations "A,B,C"`
to choose them yourself. No station is invented, duplicated, renamed or merged,
and every cost is the same `Distance_km` shortest-path cost Nearest Neighbour
optimizes.

**A QAOA run solves that k-station tour. It does not solve the full 26-station
network, and Phase 2 never reports it as if it did** — every run prints which
`k of 26` stations it covered and what the full network would cost in qubits.
The full network remains Phase 1's job.

### Simulator vs IBM Quantum

| | `--mode simulator` (default) | `--mode ibm` |
|---|---|---|
| Runs on | Qiskit Aer, local | real IBM hardware via qiskit-ibm-runtime |
| Cost | free, seconds | queue time, consumes IBM usage |
| Noise | none | real device noise |
| Credentials | none | `IBM_QUANTUM_TOKEN` from the environment |

`--mode ibm` defaults to `--ibm-strategy final-only`: the angles are trained on
the simulator and a single job with the tuned angles goes to hardware.
`--ibm-strategy full` runs every optimizer iteration on hardware inside a
`Session` — far slower and far more expensive.

### IBM credentials

Credentials are read **only** from environment variables, and are never
hardcoded, printed, logged, or committed:

```
IBM_QUANTUM_TOKEN      required    API key
IBM_QUANTUM_INSTANCE   optional    CRN / instance
IBM_QUANTUM_CHANNEL    optional    default: ibm_quantum_platform
IBM_QUANTUM_BACKEND    optional    default: least busy operational device
```

Put them in a `.env` in the project root, which `.gitignore` already excludes:

```bash
copy .env.example .env
```

then paste the key after `IBM_QUANTUM_TOKEN=`. A real environment variable
always wins over `.env`, so `set IBM_QUANTUM_TOKEN=...` overrides the file
without editing it. `.env.example` is the committed template and must stay
empty — a test asserts it carries no values.

Verify the setup without contacting IBM or spending a job:

```bash
.venv\Scripts\python.exe run_phase2.py --check-ibm
```

It reports which variables are set; for the token it prints the character count
only, never the value.

Verified against the installed packages (qiskit 2.5.2, qiskit-ibm-runtime 0.49):
the retired `ibm_quantum` channel no longer exists, circuits must be transpiled
to the target backend's ISA before submission, and `QAOAAnsatz` (the class) is
deprecated in favour of the `qaoa_ansatz` function.

## Layout

```
hybrid-quantum-energy-tsp/
├── data/                  the CSV (source of truth)
├── phase1/                Phase 1 implementation
│   ├── data_loader.py     CSV load + validation
│   ├── network.py         undirected graph + Dijkstra shortest paths
│   ├── nn_tsp.py          classical Nearest Neighbour solver
│   ├── layout.py          non-overlapping node placement
│   ├── visualize.py       network map
│   └── main.py            CLI
├── phase2/                Phase 2 implementation (quantum QAOA)
│   ├── instance.py        small TSP instance taken from the real CSV
│   ├── qubo.py            TSP -> QUBO
│   ├── ising.py           QUBO -> Ising Hamiltonian
│   ├── qaoa.py            Ising -> QAOA -> validated tour
│   ├── backends.py        Aer simulator / IBM Quantum runtime
│   ├── credentials.py     env-only IBM credentials, never echoed back
│   ├── hybrid.py          FULL-network QAOA segment reoptimization
│   ├── comparison.py      classical vs hybrid, same-problem checks
│   ├── visualize.py       full-network maps + comparison figure
│   ├── reference.py       NN + exact optimum on the same instance
│   └── main.py            CLI
├── tests/test_phase1.py   Phase 1 tests (real dataset)
├── tests/test_phase2.py   Phase 2 tests (real dataset)
├── outputs/               generated maps
├── run_phase1.py          entry point
├── run_phase2.py          entry point (QAOA)
├── backend/               FastAPI service (scaffolding, unused in Phase 1)
│   ├── app/
│   │   ├── main.py        app factory + routes wiring
│   │   ├── api/routes/    HTTP endpoints
│   │   ├── core/          config / settings
│   │   ├── dataio/        CSV loading + graph building   (Phase 1)
│   │   ├── solvers/       classical NN + QAOA            (Phase 2/3)
│   │   ├── services/      comparison, energy loss
│   │   └── schemas/       pydantic request/response models
│   ├── tests/
│   └── requirements.txt
├── frontend/              React + Tailwind               (later)
└── docs/
```

## Running the backend API (Phase 3)

Requires **Python 3.13**. Python 3.14 is not usable here: pydantic and Qiskit have
no prebuilt Windows wheels for it, so pip falls back to a Rust/MSVC source build
that fails without Visual Studio C++ build tools.

```bash
py -3.13 -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend
```

Run those from the repository root. Then open **http://127.0.0.1:8000/docs** for
the interactive OpenAPI documentation (schema at `/openapi.json`).

The API is a thin layer over Phase 1 and Phase 2: every route calls those
modules directly, so no solver, cost function or comparison is duplicated.

| method | endpoint | what it does |
|---|---|---|
| GET | `/stations` | all 26 stations, with type, coordinates and degree |
| GET | `/network` | network summary plus all 38 transmission lines |
| POST | `/stations/resolve` | check a starting station before solving |
| POST | `/solve/classical` | Phase 1 Nearest Neighbour — milliseconds |
| POST | `/solve/hybrid` | Phase 2 hybrid QAOA on the simulator — ~90 s |
| POST | `/solve/compare` | both solvers, the comparison, and the graphs |
| GET | `/graphs` | where the three images are, and whether they exist |
| GET | `/graphs/{name}` | the PNG itself (`nn_route`, `qaoa_route`, `comparison`) |
| GET | `/health`, `/dataset/status` | liveness and what CSV was loaded |

```bash
curl -X POST http://127.0.0.1:8000/solve/classical \
  -H "Content-Type: application/json" -d "{\"start\": \"Mysuru Substation\"}"
```

Notes:

- **Simulator only.** Every quantum run uses local Qiskit Aer. No endpoint
  submits an IBM Quantum job; the IBM configuration is left untouched.
- `/solve/hybrid` and `/solve/compare` are long requests at their defaults.
  Lower `sweeps`, or `window`, for a faster answer.
- An unknown or ambiguous starting station returns **422** with a machine-readable
  `error` code and suggestions, not a 500.
- `OUTPUTS_DIR` redirects where the graphs are written.
- No database and no authentication yet.

Tests — the API suite from `backend/`, the solver suites from the root:

```bash
.venv\Scripts\python.exe -m pytest -q
```

```bash
.venv\Scripts\python.exe -m unittest tests.test_phase1 tests.test_phase2
```

## Running the dashboard (Phase 4)

A React client for the API. It holds no solver logic: every distance, route and
comparison comes from the backend, and the station list is fetched, not
hardcoded.

Start the backend first (see above), then from `frontend/`:

```bash
npm install
```

```bash
npm run dev
```

Open <http://localhost:5173>. The dev server proxies the API routes to
`http://127.0.0.1:8000`, so the browser stays on one origin.

The dashboard carries the project overview, an interactive map of the 26
stations and 38 transmission lines, a starting-station selector, the run
control, both solvers' results, the comparison, both complete 26-station
itineraries, the generated figures, and an energy-loss section. The results
column also carries the route loss costing - the lines each route uses, their
modeled `Energy_Loss_MW`, and what that is worth at the verified KERC HT-2(a)
energy charge. Every run uses the local simulator; the interface cannot submit
an IBM Quantum job.

See `frontend/README.md` for the component layout and the design system.

## The project assistant (RAG)

A grounded question-answering panel over this project's own context. It lives in
the dashboard drawer, next to Routes, Energy loss, Figures and Method.

It answers from three places and nowhere else:

| Source | What it covers |
|--------|----------------|
| The transmission-line CSV | Every line and station record, and the network summary. Column values verbatim, including the derived rupee columns. |
| Project documentation | `DATASET.md`, `README.md`, `docs/PHASES.md`, `data/README.md`, and the KERC tariff provenance carried in `energy_cost/tariff.py`. |
| The run on screen | The `/solve/compare` body the dashboard is currently showing - routes, legs, runtimes, QAOA window and qubit count, backend, comparison, and the energy costing. |

It has no outside knowledge of the Karnataka grid. When the retrieved context
does not support an answer it says so and returns `grounded: false`, rather than
filling the gap. Every answer lists the sources it was built from - a CSV row, a
document heading, or a field of the current run - so a figure can be checked
rather than trusted.

The run is passed per request and is never written into the shared index, so one
session's results cannot surface in another's answer. With no run loaded the
assistant has no solver context and says so; it never describes a run it cannot
see.

### Setup

Generation runs on a **local model, via Ollama**. There is no API key, no
account and no per-question cost, and the dataset, the solver results and the
documents never leave this machine.

Once:

```bash
ollama pull llama3.2:3b
```

(Ollama itself: <https://ollama.com/download>. `llama3.2:3b` is about 2 GB and
runs on CPU; any model you have pulled works - set `ASSISTANT_MODEL` to use a
different one. A larger model answers better and runs slower.)

Then build the knowledge base:

```bash
python reindex_assistant.py
```

Re-run that whenever the project data changes - a new CSV, a tariff change
followed by `python -m energy_cost.recompute`, or an edit to any of the
documents listed above. The index is derived (`outputs/assistant_index.json`);
deleting it costs nothing.

If Ollama is not running, or the model has not been pulled, the panel says so
and shows the exact command that fixes it. It does not report a setup problem
as a gap in the project data, and it never shows a fabricated answer.

The backend refuses any `OLLAMA_HOST` that is not a loopback address, so the
project's data cannot be sent to a remote model by a configuration change.

### Endpoint

```
POST /assistant/query   { "question": "...", "run": <optional /solve/compare body> }
                     -> { "answer": "...", "sources": [...], "grounded": true, ... }
GET  /assistant/status  what is indexed, where generation runs, and whether the
                        local model has been pulled
```

Retrieval is BM25 over the project's own chunks, computed in process - no second
database and no embedding vendor. `backend/app/assistant/retrieval.py` explains
why that is the right size here and how a vector-backed retriever would drop in.

## Phase plan

| Phase | Scope | State |
|-------|-------|-------|
| 0 | Project structure, FastAPI skeleton, health check | done |
| 1 | Load the CSV, build the graph, classical Nearest Neighbour TSP, map | done |
| 2 | QAOA TSP: TSP -> QUBO -> Ising -> QAOA, Aer simulator + IBM Quantum | done |
| 3 | FastAPI backend over the Phase 1 / Phase 2 solvers | done |
| 4 | React dashboard over the Phase 3 API | done |
| 5 | Classical vs Quantum comparison | not started |
| 6 | Energy loss estimation | done (route loss costed at the verified KERC tariff - see `DATASET.md`) |
| 7 | Visualization + React frontend | done (Phase 4) |
| 8 | Auth (JWT) + optimization history (PostgreSQL/SQLite) | not started |

Each phase stops for confirmation before the next begins.

## Ground rules

- `data/transmission_lines.csv` is the only source of network data. Nothing is fabricated.
- `Distance_km` is the primary TSP optimization cost.
- The TSP formulation stays identical between the Classical and QAOA solvers.
- This project does not reuse code from any earlier implementation.
