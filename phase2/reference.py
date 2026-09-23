"""Reference answers for the *same* instance, so the QAOA tour can be judged.

Two of them:

  * the Phase 1 Nearest Neighbour tour, produced by calling Phase 1's own solver
    restricted to the selected stations - nothing is reimplemented here, so the
    classical baseline really is the Phase 1 baseline;

  * the exact optimum by brute force. At Phase 2 instance sizes there are only
    (k-1)! orderings, so the true best tour is cheap to compute. It exists to
    make the "QAOA is approximate" claim measurable rather than rhetorical.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from itertools import permutations

from phase1.nn_tsp import solve


@dataclass
class Reference:
    label: str
    route: list                 # station names, closed
    total_distance_km: float
    execution_time_s: float


def nearest_neighbour(network, instance) -> Reference:
    """Phase 1's Nearest Neighbour over exactly the instance's stations."""
    result = solve(network, instance.start, stations=list(instance.names))
    return Reference(
        label="Nearest Neighbour (Phase 1)",
        route=result.closed_route,
        total_distance_km=result.total_distance_km,
        execution_time_s=result.execution_time_s,
    )


def brute_force_optimum(instance) -> Reference:
    """The exact best tour, by enumerating every ordering."""
    started_at = time.perf_counter()
    best_order, best_distance = None, float("inf")
    for middle in permutations(range(1, instance.size)):
        order = (0,) + middle + (0,)
        distance = sum(
            instance.distance(a, b) for a, b in zip(order, order[1:])
        )
        if distance < best_distance:
            best_distance = distance
            best_order = order
    elapsed = time.perf_counter() - started_at
    return Reference(
        label="Exact optimum (brute force)",
        route=[instance.names[i] for i in best_order],
        total_distance_km=best_distance,
        execution_time_s=elapsed,
    )
