"""FastAPI application entry point.

Phase 3: the API over the existing solvers. Every route delegates to the Phase 1
and Phase 2 modules at the repository root - the classical Nearest Neighbour
solver, the hybrid QAOA reoptimizer, the comparison and the renderers are used
as they are, never reimplemented here.

No database and no authentication yet, and every quantum run uses the local
simulator.

Run it with:

    .venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --app-dir backend

Interactive documentation is at /docs, the OpenAPI schema at /openapi.json.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (assistant, graphs, health, network, solve,
                            stations)
from app.core.auth import require_user
from app.core.config import get_settings

DESCRIPTION = """
HTTP access to the hybrid quantum-classical energy-distribution TSP.

The 26-station network and its 38 transmission lines come from the project's
transmission-line CSV, which is the single source of truth and is never
modified.

**What the API does**

* `GET /stations` - every station in the dataset
* `GET /network` - the network summary and all transmission lines
* `POST /stations/resolve` - check a starting station before solving
* `POST /solve/classical` - the Phase 1 Nearest Neighbour tour
* `POST /solve/hybrid` - the Phase 2 hybrid QAOA reoptimization
* `POST /solve/compare` - both solvers, the comparison, and the graphs
* `GET /graphs` - where the generated images are, and the images themselves
* `POST /assistant/query` - grounded questions about this project

**The assistant** answers only from the project's own context: the
transmission-line dataset, the project documentation, the approved KERC
tariff reference, and the optimization run you attach to the request. It
has no outside knowledge of the Karnataka grid and says so rather than
filling a gap.

**Execution mode** - every quantum run uses the local Qiskit Aer simulator.
No endpoint submits an IBM Quantum job; the IBM configuration is left untouched.

**Timing** - the classical solver answers in milliseconds. The hybrid solver
takes roughly 90 seconds at its default settings, so `/solve/hybrid` and
`/solve/compare` are long requests. Lower `sweeps` for a faster run.
"""

TAGS_METADATA = [
    {"name": "health", "description": "Liveness and dataset status."},
    {"name": "network", "description": "Stations and transmission lines."},
    {"name": "solve", "description": "Run the solvers and compare them."},
    {"name": "graphs", "description": "The generated route and comparison maps."},
    {"name": "assistant", "description": "Grounded questions about the project."},
]


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="0.3.0",
        openapi_tags=TAGS_METADATA,
    )

    # The React dev server will live here from the frontend phase onward.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health and the service index stay open: the frontend polls health for its
    # connection indicator before a session exists, and it reveals nothing.
    app.include_router(health.router)

    # The application endpoints go through the auth dependency, which admits the
    # demo user while AUTH_MODE=demo and demands a valid Supabase token under
    # AUTH_MODE=supabase. It runs before any handler, so the gate never touches
    # the solver or the dataset - the optimization logic is untouched, only
    # fronted.
    protected = [Depends(require_user)]
    app.include_router(stations.router, dependencies=protected)
    app.include_router(network.router, dependencies=protected)
    app.include_router(solve.router, dependencies=protected)
    # The assistant reads the same dataset and the caller's own run, so it
    # is gated exactly like the endpoints that produced them.
    app.include_router(assistant.router, dependencies=protected)

    # The graphs router guards its own listing; the raw PNG at /graphs/{name} is
    # left open because it is loaded by an <img> element, which cannot send an
    # Authorization header, and it exposes only a rendered route map that a
    # protected /solve/compare had to produce in the first place.
    app.include_router(graphs.router)

    @app.get("/", tags=["root"], summary="Service index")
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": app.version,
            "phase": "3 - FastAPI backend",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/health",
            "endpoints": {
                "stations": "/stations",
                "resolve_start": "/stations/resolve",
                "network": "/network",
                "solve_classical": "/solve/classical",
                "solve_hybrid": "/solve/hybrid",
                "compare": "/solve/compare",
                "graphs": "/graphs",
                "assistant_query": "/assistant/query",
                "assistant_status": "/assistant/status",
            },
            "execution_mode": "simulator",
        }

    return app


app = create_app()
