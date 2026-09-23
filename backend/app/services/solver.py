"""Orchestration over the existing Phase 1 and Phase 2 solvers.

Every distance, route, validation check and comparison figure the API returns is
produced by those modules:

    phase1.nn_tsp.solve            the classical Nearest Neighbour tour
    phase2.hybrid.hybrid_solve     the hybrid QAOA reoptimization loop
    phase2.hybrid.validate_full_tour  the 26-station tour checks
    phase2.comparison.build_comparison / same_problem_checks
    phase2.visualize.render_route_map / render_comparison

The route energy-loss costing comes from `energy_cost.compare_routes`, which
reads the CSV's own `Energy_Loss_MW` values off the lines each route uses and
prices them at the verified KERC tariff. It is an ANALYSIS of the tours the
solvers already chose: both still minimize the same `Distance_km` objective,
and energy loss is not part of either cost function.

This layer resolves the starting station, calls them, and reshapes the results
for JSON. It implements no optimization of its own and changes no algorithm.

Execution mode is fixed to the local simulator. `make_runner` is only ever
called with "simulator", so no endpoint can submit an IBM Quantum job.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from phase1.nn_tsp import SolverError, resolve_station
from phase1.nn_tsp import solve as nn_solve
from phase2.backends import make_runner
from phase2.comparison import build_comparison, same_problem_checks
from phase2.hybrid import hybrid_solve, validate_full_tour
from phase2.visualize import (NN_LEGEND, NN_TITLE, QAOA_LEGEND, QAOA_TITLE,
                              render_comparison, render_route_map)

from energy_cost import compare_routes

from app.core.config import get_settings
from app.dataio.network import get_dataset, get_network

# The API never runs on hardware. Phase 2's IBM path and its credentials are
# left exactly as they are; this module simply never selects them.
EXECUTION_MODE = "simulator"

GRAPH_FILES = {
    "nn_route": "nn_full_route.png",
    "qaoa_route": "qaoa_full_route.png",
    "comparison": "nn_vs_qaoa_comparison.png",
}


class InvalidStartStation(Exception):
    """The requested starting station could not be resolved to exactly one."""

    def __init__(self, message: str, code: str, suggestions: list):
        super().__init__(message)
        self.message = message
        self.code = code
        self.suggestions = suggestions


@dataclass
class HybridSettings:
    """Resolved hybrid parameters: request overrides on top of the defaults."""

    window: int
    sweeps: int
    reps: int
    shots: int
    maxiter: int
    restarts: int
    cvar: float
    seed: int
    prune: bool


def hybrid_settings(options=None) -> HybridSettings:
    """Fill unset request fields from the configured Phase 2 defaults."""
    settings = get_settings()

    def pick(name: str, fallback):
        value = getattr(options, name, None) if options is not None else None
        return fallback if value is None else value

    return HybridSettings(
        window=pick("window", settings.qaoa_window),
        sweeps=pick("sweeps", settings.qaoa_sweeps),
        reps=pick("reps", settings.qaoa_reps),
        shots=pick("shots", settings.qaoa_shots),
        maxiter=pick("maxiter", settings.qaoa_maxiter),
        restarts=pick("restarts", settings.qaoa_restarts),
        cvar=pick("cvar", settings.qaoa_cvar),
        seed=pick("seed", settings.qaoa_seed),
        prune=pick("prune", True),
    )


# --------------------------------------------------------------- stations ---

def resolve_start(network, name: str) -> str:
    """Normalize a requested start using Phase 1's own resolver.

    Phase 1 decides what matches; the extra lookup here only classifies the
    failure and offers suggestions, so the caller gets a useful error instead
    of a bare 500.
    """
    try:
        return resolve_station(network, name)
    except SolverError as exc:
        query = str(name or "").strip().lower()
        matches = [n for n in network.names if query and query in n.lower()]
        code = ("ambiguous_start_station" if len(matches) > 1
                else "unknown_start_station")
        raise InvalidStartStation(str(exc), code, matches[:10]) from exc


def station_degree(network, name: str) -> int:
    return len(network.adjacency.get(name, {}))


# ---------------------------------------------------------------- solvers ---

def run_classical(start: str):
    """Phase 1 Nearest Neighbour over the full network, plus its tour checks."""
    network = get_network()
    resolved = resolve_start(network, start)
    result = nn_solve(network, resolved)
    checks = validate_full_tour(network, result, resolved, network.names)
    return network, resolved, result, checks


def run_hybrid(start: str, options=None):
    """Phase 2 hybrid QAOA over the full network, on the local simulator.

    Starts from the same Nearest Neighbour tour the CLI starts from, so the
    classical result is returned alongside it rather than recomputed.
    """
    network, resolved, nn_result, nn_checks = run_classical(start)
    config = hybrid_settings(options)

    runner = make_runner(EXECUTION_MODE, seed=config.seed)
    try:
        hybrid_result = hybrid_solve(
            network, nn_result.order, runner,
            window=config.window, sweeps=config.sweeps, prune=config.prune,
            reps=config.reps, shots=config.shots, maxiter=config.maxiter,
            restarts=config.restarts, seed=config.seed, cvar_alpha=config.cvar,
            progress=None,      # the API returns results, not a progress log
        )
    finally:
        runner.close()

    hybrid_checks = validate_full_tour(
        network, hybrid_result.tour, resolved, network.names
    )
    return {
        "network": network,
        "start": resolved,
        "config": config,
        "nn_result": nn_result,
        "nn_checks": nn_checks,
        "hybrid_result": hybrid_result,
        "hybrid_checks": hybrid_checks,
    }


def run_comparison(start: str, options=None, render_graphs: bool = True) -> dict:
    """Both solvers, the Phase 2 comparison, and optionally the three images."""
    run = run_hybrid(start, options)
    network = run["network"]

    comparison = build_comparison(
        network, get_dataset(),
        run["nn_result"], run["nn_checks"],
        run["hybrid_result"], run["hybrid_checks"], run["start"],
    )
    problem_checks = same_problem_checks(
        network, run["nn_result"], run["hybrid_result"], run["start"]
    )

    # Same network, same two tours, same tariff for both sides - so the energy
    # figures are comparable for exactly the reason the distances are.
    energy = compare_routes(network, run["nn_result"], run["hybrid_result"])

    graphs = {}
    if render_graphs:
        graphs = render_all_graphs(
            network, run["nn_result"], run["hybrid_result"], comparison
        )

    run["comparison"] = comparison
    run["problem_checks"] = problem_checks
    run["energy"] = energy
    run["graphs"] = graphs
    return run


# ----------------------------------------------------------------- graphs ---

def render_all_graphs(network, nn_result, hybrid_result, comparison) -> dict:
    """Write the two route maps and the comparison figure.

    Same renderers, same titles and the same displayed distances the Phase 2
    CLI uses, so the API and the command line produce identical images.
    """
    outputs = get_settings().outputs_path
    os.makedirs(outputs, exist_ok=True)

    nn_png = str(outputs / GRAPH_FILES["nn_route"])
    qaoa_png = str(outputs / GRAPH_FILES["qaoa_route"])
    comparison_png = str(outputs / GRAPH_FILES["comparison"])

    render_route_map(network, nn_result, nn_png,
                     f"{NN_TITLE} - {comparison.nn_distance_display:,.1f} km",
                     route_label=NN_LEGEND)
    render_route_map(network, hybrid_result.tour, qaoa_png,
                     f"{QAOA_TITLE} - "
                     f"{comparison.hybrid_distance_display:,.1f} km",
                     route_label=QAOA_LEGEND)
    render_comparison(nn_png, qaoa_png, comparison, comparison_png)

    return {"nn_route": nn_png, "qaoa_route": qaoa_png,
            "comparison": comparison_png}


def graph_path(name: str):
    """Absolute path of one known graph, or None for an unknown name.

    Only the three names in `GRAPH_FILES` resolve, so a request can never
    reach a file outside the outputs folder.
    """
    filename = GRAPH_FILES.get(name)
    if filename is None:
        return None
    return get_settings().outputs_path / filename
