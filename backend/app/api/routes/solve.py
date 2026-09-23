"""Solver endpoints.

All three run the existing solvers from `phase1` and `phase2`. The hybrid ones
always use the local Qiskit Aer simulator - no endpoint can submit an IBM
Quantum job.

These are plain `def` handlers, so FastAPI runs them on its threadpool and a
long hybrid run does not block the event loop.
"""

from fastapi import APIRouter

from phase1.data_loader import DatasetError
from phase1.network import NetworkError
from phase2.backends import BackendError

from app.api import errors
from app.core.config import get_settings
from app.schemas.solver import (ClassicalSolveOut, CompareOut, CompareRequest,
                                HybridRequest, HybridSolveOut, StartRequest)
from app.services.serialize import (classical_out, comparison_out, graphs_out,
                                    hybrid_out, route_energy_comparison_out)
from app.services.solver import (InvalidStartStation, run_classical,
                                 run_comparison, run_hybrid)

router = APIRouter(prefix="/solve", tags=["solve"])

COMMON_ERRORS = {
    422: {"description": "Unknown or ambiguous starting station."},
    409: {"description": "The network cannot support the requested tour."},
    503: {"description": "Dataset unavailable."},
}


@router.post(
    "/classical",
    response_model=ClassicalSolveOut,
    summary="Run the classical Nearest Neighbour solver",
    description="Phase 1's `nn_tsp.solve` over the full 26-station network. "
                "Returns the tour, every leg, the total distance, the "
                "execution time and the validation checks. Completes in "
                "milliseconds.",
    responses=COMMON_ERRORS,
)
def solve_classical(request: StartRequest) -> ClassicalSolveOut:
    try:
        _, start, result, checks = run_classical(request.start)
    except InvalidStartStation as exc:
        raise errors.invalid_start(exc) from exc
    except DatasetError as exc:
        raise errors.dataset_unavailable(exc) from exc
    except NetworkError as exc:
        raise errors.network_unusable(exc) from exc

    return classical_out(start, result, checks)


@router.post(
    "/hybrid",
    response_model=HybridSolveOut,
    summary="Run the hybrid QAOA simulator",
    description="Phase 2's `hybrid.hybrid_solve`: QAOA is the optimization "
                "engine inside a classical full-network reoptimization loop, "
                "started from the Nearest Neighbour tour and run on the local "
                "Qiskit Aer simulator.\n\n"
                "**This is slow.** At the default window W=4 a full run takes "
                "roughly 90 seconds. Lower `sweeps` for a quicker answer.\n\n"
                "No IBM Quantum job is ever submitted.",
    responses=COMMON_ERRORS,
)
def solve_hybrid(request: HybridRequest) -> HybridSolveOut:
    try:
        run = run_hybrid(request.start, request)
    except InvalidStartStation as exc:
        raise errors.invalid_start(exc) from exc
    except DatasetError as exc:
        raise errors.dataset_unavailable(exc) from exc
    except NetworkError as exc:
        raise errors.network_unusable(exc) from exc
    except BackendError as exc:
        raise errors.dataset_unavailable(exc) from exc

    return hybrid_out(run["start"], run["hybrid_result"], run["hybrid_checks"])


@router.post(
    "/compare",
    response_model=CompareOut,
    summary="Run both solvers and compare them",
    description="Runs the classical Nearest Neighbour solver and the hybrid "
                "QAOA reoptimizer on the same network from the same starting "
                "station, returns Phase 2's comparison, and writes the two "
                "route maps and the comparison figure.\n\n"
                "The difference and the percentage are derived from the "
                "displayed distances, so they can be recomputed from the two "
                "numbers returned.\n\n"
                "`energy` costs the modeled transmission loss on each route: "
                "the lines each tour actually uses, their `Energy_Loss_MW` "
                "from the dataset, and what that is worth at the verified "
                "KERC HT-2(a) energy charge. It is an analysis of the routes "
                "the solvers chose - neither optimizes for loss.\n\n"
                "**This is slow** for the same reason as `/solve/hybrid`. Set "
                "`render_graphs: false` to skip drawing the images.",
    responses=COMMON_ERRORS,
)
def solve_compare(request: CompareRequest) -> CompareOut:
    try:
        run = run_comparison(request.start, request,
                             render_graphs=request.render_graphs)
    except InvalidStartStation as exc:
        raise errors.invalid_start(exc) from exc
    except DatasetError as exc:
        raise errors.dataset_unavailable(exc) from exc
    except NetworkError as exc:
        raise errors.network_unusable(exc) from exc
    except BackendError as exc:
        raise errors.dataset_unavailable(exc) from exc

    return CompareOut(
        start=run["start"],
        classical=classical_out(run["start"], run["nn_result"],
                                run["nn_checks"]),
        hybrid=hybrid_out(run["start"], run["hybrid_result"],
                          run["hybrid_checks"]),
        comparison=comparison_out(run["comparison"], run["problem_checks"]),
        energy=route_energy_comparison_out(run["energy"]),
        graphs=graphs_out(str(get_settings().outputs_path), run["graphs"]),
    )
