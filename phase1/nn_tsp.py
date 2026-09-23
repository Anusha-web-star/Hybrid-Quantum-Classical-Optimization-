"""Classical Nearest Neighbour TSP solver.

The greedy construction heuristic:

    1. Stand at the chosen starting station.
    2. Of the stations not yet visited, move to the nearest one.
    3. Repeat until every station has been visited exactly once.
    4. Return from the last station to the start, closing the tour.

Distances come from `Network.travel_cost`, i.e. the shortest chain of real
transmission lines between two stations, measured in `Distance_km`.

This is O(n^2) and gives no optimality guarantee - it is the classical baseline
that the quantum solver will later be compared against.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .network import Network, NetworkError


class SolverError(Exception):
    """The solver was asked for something it cannot deliver."""


@dataclass
class Leg:
    """One hop of the tour, from one station in the visiting order to the next."""

    step: int
    origin: str
    destination: str
    distance_km: float
    path: list          # stations physically traversed, including both ends
    is_direct: bool     # True if a single transmission line joins the two

    @property
    def via(self) -> list:
        """Intermediate stations passed through without being 'visited' yet."""
        return self.path[1:-1]


@dataclass
class TourResult:
    """Outcome of one Nearest Neighbour run."""

    start: str
    order: list                 # visiting order, start listed once at the front
    legs: list                  # list[Leg], len == len(order); last leg closes the tour
    total_distance_km: float
    execution_time_s: float
    stations_visited: int

    @property
    def closed_route(self) -> list:
        """Visiting order with the start repeated at the end."""
        return self.order + [self.start]

    @property
    def physical_path(self) -> list:
        """Every station traversed in order, including pass-throughs."""
        path = [self.start]
        for leg in self.legs:
            path.extend(leg.path[1:])
        return path

    @property
    def direct_legs(self) -> int:
        return sum(1 for leg in self.legs if leg.is_direct)


def resolve_station(network: Network, name: str) -> str:
    """Map user input to a real station name, or explain why it does not match."""
    if name is None or not str(name).strip():
        raise SolverError("No starting station given.")

    query = str(name).strip()
    if query in network.stations:
        return query

    lowered = query.lower()
    exact = [n for n in network.names if n.lower() == lowered]
    if len(exact) == 1:
        return exact[0]

    partial = [n for n in network.names if lowered in n.lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise SolverError(
            f"'{query}' matches {len(partial)} stations: "
            + ", ".join(partial)
            + ". Please be more specific."
        )

    raise SolverError(
        f"'{query}' is not a station in this dataset. "
        f"Run with --list to see all {len(network.names)} station names."
    )


def solve(
    network: Network,
    start: str,
    stations: Optional[list] = None,
) -> TourResult:
    """Run Nearest Neighbour from `start` over `stations` (default: all of them).

    Raises `SolverError` for an unknown start and `NetworkError` when the
    stations cannot all be reached from one another.
    """
    start = resolve_station(network, start)

    pool = list(stations) if stations else list(network.names)
    if start not in pool:
        raise SolverError(
            f"'{start}' is not part of the selected station set."
        )
    if len(pool) < 2:
        raise SolverError(
            "A tour needs at least 2 stations; the dataset provides "
            f"{len(pool)}."
        )

    # Fail before timing rather than mid-route: every station must be reachable.
    unreachable = [
        n for n in pool
        if n != start and network.travel_cost(start, n) == float("inf")
    ]
    if unreachable:
        preview = ", ".join(sorted(unreachable)[:8])
        more = " ..." if len(unreachable) > 8 else ""
        raise NetworkError(
            f"{len(unreachable)} station(s) cannot be reached from '{start}' "
            f"over the transmission lines in the dataset: {preview}{more}\n"
            f"The network is disconnected, so no closed tour of all stations "
            f"exists. Use --component N to route within one connected group."
        )

    started_at = time.perf_counter()

    unvisited = set(pool)
    unvisited.remove(start)
    order = [start]
    legs = []
    current = start
    total = 0.0

    while unvisited:
        # Step 2: nearest unvisited station. Ties broken by name, so a given
        # dataset and start always produce the same tour.
        nearest = min(unvisited, key=lambda n: (network.travel_cost(current, n), n))
        cost = network.travel_cost(current, nearest)

        legs.append(
            Leg(
                step=len(legs) + 1,
                origin=current,
                destination=nearest,
                distance_km=cost,
                path=network.travel_path(current, nearest),
                is_direct=network.is_direct_line(current, nearest),
            )
        )
        total += cost
        order.append(nearest)
        unvisited.remove(nearest)
        current = nearest

    # Step 4: close the tour.
    closing_cost = network.travel_cost(current, start)
    legs.append(
        Leg(
            step=len(legs) + 1,
            origin=current,
            destination=start,
            distance_km=closing_cost,
            path=network.travel_path(current, start),
            is_direct=network.is_direct_line(current, start),
        )
    )
    total += closing_cost

    elapsed = time.perf_counter() - started_at

    return TourResult(
        start=start,
        order=order,
        legs=legs,
        total_distance_km=total,
        execution_time_s=elapsed,
        stations_visited=len(order),
    )
