"""Hybrid quantum-classical solver for the FULL 26-station network.

What this is
------------
QAOA cannot take the whole network in one circuit: the position-encoded TSP QUBO
needs (n-1)^2 = 625 qubits and ~29,400 ZZ couplings for n=26, which is far beyond
any available device (see docs/PHASES.md for the resource analysis). Rather than
pretend a 5-station subproblem is the answer, this module uses QAOA as the
**optimization engine inside a full-network reoptimization loop**:

    1. Start from a complete 26-station tour (the Phase 1 Nearest Neighbour one).
    2. Slide a window along the tour: `window` consecutive stations, with the
       station before and the station after the window held fixed.
    3. Hand that window to QAOA as an open path-TSP subproblem - order the free
       stations between the fixed entry and the fixed exit - using w^2 qubits.
    4. Accept the new ordering when it shortens the tour, otherwise keep the old.
    5. Sweep until no window yields an improvement.

Every intermediate state is a complete, valid 26-station tour, so the output is
a full-network route directly comparable with Nearest Neighbour.

What this is not
----------------
This is **not** a claim of quantum advantage, and the QAOA subproblems do not
independently solve the whole TSP. The decomposition - which windows to try, and
whether to accept a result - is classical. QAOA's contribution is solving each
window subproblem. On this dataset it does that job well: a W=4 hybrid run
reaches exactly the same tour as an exhaustive brute-force subsolver over the
same windows, so QAOA is solving its subproblems optimally. The limiting factor
is the window neighbourhood, not the quantum optimizer.

Costs are `phase1.network.Network.travel_cost` throughout - the same
`Distance_km` shortest-path costs Nearest Neighbour minimises.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from phase1.nn_tsp import Leg, TourResult

from .qaoa import solve_qubo_qaoa
from .qubo import build_path_qubo


@dataclass
class HybridResult:
    """The full-network hybrid outcome, plus how the search got there."""

    tour: TourResult                # plot- and validate-compatible with Phase 1
    start_distance_km: float        # the tour we started from (Phase 1 NN)
    window: int
    sweeps_run: int
    subproblems_solved: int
    subproblems_skipped: int
    improvements_accepted: int
    qaoa_evaluations: int
    qubits_per_subproblem: int
    execution_time_s: float
    mode: str = "simulator"
    backend_name: str = ""
    backend_description: str = ""
    job_ids: list = field(default_factory=list)

    @property
    def total_distance_km(self) -> float:
        return self.tour.total_distance_km

    @property
    def improvement_km(self) -> float:
        return self.start_distance_km - self.total_distance_km

    @property
    def improvement_percent(self) -> float:
        if not self.start_distance_km:
            return 0.0
        return self.improvement_km / self.start_distance_km * 100.0


def tour_result_from_order(network, order: list, elapsed: float) -> TourResult:
    """Build a Phase 1 `TourResult` from a visiting order.

    Uses exactly the structures Phase 1's solver produces, so the same validator
    and the same renderer work on a hybrid tour without changing Phase 1.
    """
    legs = []
    total = 0.0
    closed = list(order) + [order[0]]
    for step, (origin, destination) in enumerate(zip(closed, closed[1:]), start=1):
        cost = network.travel_cost(origin, destination)
        legs.append(
            Leg(
                step=step,
                origin=origin,
                destination=destination,
                distance_km=cost,
                path=network.travel_path(origin, destination),
                is_direct=network.is_direct_line(origin, destination),
            )
        )
        total += cost
    return TourResult(
        start=order[0],
        order=list(order),
        legs=legs,
        total_distance_km=total,
        execution_time_s=elapsed,
        stations_visited=len(order),
    )


def tour_length(network, order: list) -> float:
    """Closed-tour length of a visiting order, in km."""
    closed = list(order) + [order[0]]
    return sum(network.travel_cost(a, b) for a, b in zip(closed, closed[1:]))


def _segment_length(network, sequence: list) -> float:
    return sum(network.travel_cost(a, b) for a, b in zip(sequence, sequence[1:]))


def reoptimize_window(network, entry: str, free: list, exit_station: str,
                      runner, **qaoa_options):
    """QAOA-order `free` between the fixed `entry` and `exit_station`.

    Returns (best_ordering, best_segment_km, evaluations). The ordering is None
    when QAOA produced no feasible assignment at all.
    """
    size = len(free)
    entry_cost = [network.travel_cost(entry, name) for name in free]
    exit_cost = [network.travel_cost(name, exit_station) for name in free]
    pair_cost = [
        [network.travel_cost(a, b) for b in free] for a in free
    ]

    involved = free + [entry, exit_station]
    longest = max(
        network.travel_cost(a, b) for a in involved for b in involved
    )
    penalty = max(1.0, (size + 2) * longest)

    qubo, encoding = build_path_qubo(entry_cost, exit_cost, pair_cost, penalty)

    def decode(bits):
        order = encoding.decode(bits)
        return None if order is None else [free[i] for i in order]

    def score(ordering):
        return _segment_length(network, [entry] + list(ordering) + [exit_station])

    return solve_qubo_qaoa(qubo, decode, score, runner, **qaoa_options)


def hybrid_solve(
    network,
    start_order: list,
    runner,
    *,
    window: int = 4,
    sweeps: int = 3,
    prune: bool = True,
    progress=None,
    **qaoa_options,
) -> HybridResult:
    """Improve a complete tour by QAOA-reoptimizing sliding windows of it.

    `start_order` is a full visiting order (Phase 1's Nearest Neighbour tour).
    The returned tour visits the same stations, starts and ends at the same
    station, and is never longer than the one it started from.

    `prune` enables don't-look bits: a window whose seven stations are all
    unchanged since it last failed to improve cannot suddenly improve, so it is
    skipped. Verified against unpruned sweeps with an exact subsolver - same
    tour, ~45% fewer subproblems - which matters at W=5, where each subproblem
    costs about a minute to simulate.
    """
    if window < 2:
        raise ValueError("The window must hold at least 2 free stations.")
    if window + 2 > len(start_order):
        raise ValueError(
            f"A window of {window} plus its two fixed ends does not fit in a "
            f"{len(start_order)}-station tour."
        )

    started_at = time.perf_counter()
    tour = list(start_order)
    initial_length = tour_length(network, tour)

    solved = accepted = evaluations = skipped = 0
    sweeps_run = 0
    dirty = set(tour)          # don't-look bits: every station starts "dirty"

    for sweep in range(max(1, sweeps)):
        sweeps_run += 1
        improved = False
        # The start stays at index 0: every window is taken from the positions
        # after it, wrapping around the tour.
        for offset in range(len(tour)):
            entry = tour[offset % len(tour)]
            slots = [(offset + 1 + k) % len(tour) for k in range(window)]
            free = [tour[i] for i in slots]
            exit_station = tour[(offset + 1 + window) % len(tour)]
            involved = [entry] + free + [exit_station]

            if prune and not any(name in dirty for name in involved):
                skipped += 1
                continue

            current = _segment_length(network, involved)
            ordering, length, evals = reoptimize_window(
                network, entry, free, exit_station, runner, **qaoa_options
            )
            solved += 1
            evaluations += evals

            if ordering is not None and length < current - 1e-9:
                for slot, name in zip(slots, ordering):
                    tour[slot] = name
                accepted += 1
                improved = True
                if prune:
                    dirty.update(involved)
            elif prune:
                dirty.discard(entry)

            if progress is not None:
                progress(sweep + 1, offset + 1, tour_length(network, tour))

        if not improved:
            break

    # Keep the requested starting station at the front of the reported order.
    anchor = start_order[0]
    pivot = tour.index(anchor)
    tour = tour[pivot:] + tour[:pivot]

    elapsed = time.perf_counter() - started_at

    return HybridResult(
        tour=tour_result_from_order(network, tour, elapsed),
        start_distance_km=initial_length,
        window=window,
        sweeps_run=sweeps_run,
        subproblems_solved=solved,
        subproblems_skipped=skipped,
        improvements_accepted=accepted,
        qaoa_evaluations=evaluations,
        qubits_per_subproblem=window ** 2,
        execution_time_s=elapsed,
        mode=runner.mode,
        backend_name=runner.backend_name,
        backend_description=runner.describe(),
        job_ids=list(getattr(runner, "job_ids", [])),
    )


def validate_full_tour(network, result, start: str, expected: list) -> list:
    """Every check a full-network tour must pass before it is drawn or reported.

    Returns (label, passed) pairs.
    """
    order = list(result.order)
    closed = result.closed_route
    recomputed = tour_length(network, order) if order else float("inf")

    finite_legs = all(
        leg.distance_km < float("inf") and len(leg.path) >= 2
        and leg.path[0] == leg.origin and leg.path[-1] == leg.destination
        for leg in result.legs
    )

    return [
        (f"all {len(expected)} stations present, none invented",
         sorted(order) == sorted(expected)),
        (f"{len(expected)} unique stations, none repeated",
         len(order) == len(set(order)) == len(expected)),
        (f"starts at the requested station ({start})",
         bool(order) and order[0] == start),
        ("returns to the starting station",
         len(closed) == len(order) + 1 and closed[-1] == start),
        ("every leg has a real transmission-line path and a finite cost",
         finite_legs),
        ("reported total matches the recomputed route length",
         abs(result.total_distance_km - recomputed) < 1e-6),
    ]
