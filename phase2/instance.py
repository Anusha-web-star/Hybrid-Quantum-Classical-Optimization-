"""Select a small TSP instance out of the real, complete transmission network.

Why a subset at all
-------------------
The standard position-encoded TSP QUBO needs one binary variable per
(station, tour position) pair, so it grows as **O(n^2) variables** - and one
qubit per variable. With the start pinned to position 0 that is (n-1)^2 qubits:

        n =  4 stations ->    9 qubits
        n =  5 stations ->   16 qubits
        n = 26 stations ->  625 qubits   <- the full network

625 qubits is far beyond the Aer simulator (a 2^625 statevector) and beyond any
device available today. Phase 2 therefore runs QAOA on a **sub-instance** of k
stations. This is a limit of quantum hardware and of the QUBO encoding, not a
limit of the dataset.

What the subset is, and is not
------------------------------
The k stations are chosen **directly from the full CSV** - the same 26 stations
and 38 transmission lines Phase 1 loads, unmodified. No station is invented,
duplicated, renamed or merged, and every cost is
`phase1.network.Network.travel_cost`: the shortest chain of real transmission
lines, identical to what Nearest Neighbour optimizes.

A QAOA run over k stations solves *that* k-station tour. It does not solve the
full 26-station network, and Phase 2 never reports it as though it does. The
full network continues to be solved classically by Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from phase1.network import Network, NetworkError
from phase1.nn_tsp import SolverError, resolve_station


@dataclass
class TspInstance:
    """A k-station TSP instance drawn from the dataset.

    `names[0]` is the starting station; the tour must return to it.
    `matrix[i][j]` is the travel cost in km between `names[i]` and `names[j]`.
    """

    start: str
    names: list             # names[0] == start
    matrix: list            # k x k, symmetric, zero diagonal
    selection: str          # how the stations were chosen (for the report)

    # The full network this subset was drawn from, carried so every report can
    # state plainly what fraction of the real dataset the run covers.
    total_stations: int = 0
    total_lines: int = 0

    @property
    def size(self) -> int:
        return len(self.names)

    @property
    def num_qubits(self) -> int:
        """Qubits needed by the position-encoded QUBO with the start fixed."""
        return (self.size - 1) ** 2

    @property
    def is_subset(self) -> bool:
        """True when this instance covers only part of the full network."""
        return bool(self.total_stations) and self.size < self.total_stations

    @property
    def full_network_qubits(self) -> int:
        """Qubits the same encoding would need for the *whole* network."""
        if self.total_stations < 2:
            return 0
        return (self.total_stations - 1) ** 2

    def distance(self, i: int, j: int) -> float:
        return self.matrix[i][j]

    def route_distance(self, route: list) -> float:
        """Total km for a closed route given as station names."""
        index = {name: i for i, name in enumerate(self.names)}
        total = 0.0
        for a, b in zip(route, route[1:]):
            total += self.matrix[index[a]][index[b]]
        return total

    @property
    def max_distance(self) -> float:
        return max((max(row) for row in self.matrix), default=0.0)


def _cost_matrix(network: Network, names: list) -> list:
    """Travel costs between every pair, straight from Phase 1's graph."""
    size = len(names)
    matrix = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i + 1, size):
            cost = network.travel_cost(names[i], names[j])
            if cost == float("inf"):
                raise NetworkError(
                    f"'{names[i]}' and '{names[j]}' are not connected by any "
                    f"chain of transmission lines; they cannot share a tour."
                )
            matrix[i][j] = cost
            matrix[j][i] = cost
    return matrix


def nearest_stations(network: Network, start: str, size: int) -> list:
    """The `size - 1` stations closest to `start`, plus `start` itself.

    Closeness is travel cost over real lines, and ties break by name, so the
    same dataset and start always produce the same instance.
    """
    others = [n for n in network.names if n != start]
    reachable = [n for n in others if network.travel_cost(start, n) < float("inf")]
    if len(reachable) < size - 1:
        raise NetworkError(
            f"Only {len(reachable) + 1} stations are reachable from '{start}'; "
            f"cannot build an instance of {size}."
        )
    reachable.sort(key=lambda n: (network.travel_cost(start, n), n))
    return [start] + reachable[: size - 1]


def build_instance(
    network: Network,
    start: str,
    size: int = 5,
    stations: Optional[list] = None,
) -> TspInstance:
    """Build the QAOA sub-instance.

    `stations` names the stations explicitly; otherwise the `size - 1` stations
    nearest to `start` are used.
    """
    start = resolve_station(network, start)

    if stations:
        names = [resolve_station(network, s) for s in stations]
        if start not in names:
            names = [start] + names
        seen, unique = set(), []
        for name in names:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        names = [start] + [n for n in unique if n != start]
        selection = "explicit --stations list"
    else:
        if size < 3:
            raise SolverError(
                f"A closed tour needs at least 3 stations; got {size}."
            )
        names = nearest_stations(network, start, size)
        selection = f"{size - 1} stations nearest to the start, by travel cost"

    if len(names) < 3:
        raise SolverError(
            f"A closed tour needs at least 3 stations; got {len(names)}."
        )

    summary = network.summary()
    return TspInstance(
        start=start,
        names=names,
        matrix=_cost_matrix(network, names),
        selection=selection,
        total_stations=summary["stations"],
        total_lines=summary["routable_lines"],
    )
