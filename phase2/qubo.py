"""Step 1 of the pipeline: TSP -> QUBO.

Position encoding
-----------------
A tour over k stations is a permutation. Binary variable `x[i][t]` is 1 when
station `i` occupies position `t` of the tour.

The starting station is pinned to position 0 (Nearest Neighbour also starts from
a station the user chooses, so the two solvers optimize the same thing). That
leaves k-1 free stations and k-1 free positions, so the model needs

    n = (k - 1)^2  binary variables -> (k - 1)^2 qubits.

Objective
---------
Total tour length, in `Distance_km`, over the closed route
start -> pos 1 -> ... -> pos k-1 -> start:

    sum_i  d(start, i) * x[i][1]                       leaving the start
  + sum_t sum_{i != j} d(i, j) * x[i][t] * x[j][t+1]   the middle legs
  + sum_i  d(i, start) * x[i][k-1]                     closing the tour

Constraints as penalties
------------------------
QUBO has no constraints, so "exactly one" is added as a squared penalty with
weight A:

    A * sum_i ( sum_t x[i][t] - 1 )^2      each station gets exactly one position
  + A * sum_t ( sum_i x[i][t] - 1 )^2      each position holds exactly one station

Because x is binary, x^2 = x, so ( sum_v x_v - 1 )^2 expands to
    -sum_v x_v + 2 * sum_{v<w} x_v x_w + 1.

A is chosen large enough that breaking a constraint always costs more than any
distance it could save; the default is k * (largest pairwise distance).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QUBO:
    """Minimize  sum_v linear[v] x_v + sum_{v<w} quadratic[v,w] x_v x_w + offset."""

    num_vars: int
    linear: dict = field(default_factory=dict)      # v -> coefficient
    quadratic: dict = field(default_factory=dict)   # (v, w) with v < w -> coefficient
    offset: float = 0.0

    def add_linear(self, v: int, coeff: float) -> None:
        if coeff:
            self.linear[v] = self.linear.get(v, 0.0) + coeff

    def add_quadratic(self, v: int, w: int, coeff: float) -> None:
        if v == w:                    # x^2 == x for binary variables
            self.add_linear(v, coeff)
            return
        if not coeff:
            return
        key = (v, w) if v < w else (w, v)
        self.quadratic[key] = self.quadratic.get(key, 0.0) + coeff

    def add_exactly_one(self, variables: list, weight: float) -> None:
        """Penalty  weight * (sum_v x_v - 1)^2  over `variables`."""
        for v in variables:
            self.add_linear(v, -weight)
        for a in range(len(variables)):
            for b in range(a + 1, len(variables)):
                self.add_quadratic(variables[a], variables[b], 2.0 * weight)
        self.offset += weight

    def energy(self, bits) -> float:
        """QUBO value of an assignment given as a sequence of 0/1."""
        total = self.offset
        for v, coeff in self.linear.items():
            if bits[v]:
                total += coeff
        for (v, w), coeff in self.quadratic.items():
            if bits[v] and bits[w]:
                total += coeff
        return total

    @property
    def num_terms(self) -> int:
        return len(self.linear) + len(self.quadratic)


@dataclass
class Encoding:
    """Maps (station index, tour position) to a QUBO variable index.

    Station index 0 is the start and is *not* encoded - it is pinned to position
    0. Free stations are 1..k-1 and free positions are 1..k-1.
    """

    size: int          # k, the number of stations including the start

    @property
    def free(self) -> int:
        return self.size - 1

    @property
    def num_vars(self) -> int:
        return self.free ** 2

    def var(self, station: int, position: int) -> int:
        """Variable index for station `station` (1..k-1) at position `position`."""
        return (station - 1) * self.free + (position - 1)

    def decode(self, bits) -> list:
        """Assignment -> visiting order of station indices, or None if invalid.

        Returns the full order starting and ending at station 0, e.g.
        [0, 3, 1, 2, 0]. Returns None when the bits are not a permutation.
        """
        positions = {}
        for station in range(1, self.size):
            chosen = [t for t in range(1, self.size) if bits[self.var(station, t)]]
            if len(chosen) != 1:
                return None            # station visited zero times or more than once
            positions[station] = chosen[0]
        if len(set(positions.values())) != self.free:
            return None                # two stations share a position
        order = [0] + [s for s, _ in sorted(positions.items(), key=lambda kv: kv[1])]
        return order + [0]


@dataclass
class PathEncoding:
    """Maps (station, position) to a variable for an OPEN path subproblem.

    Used by the hybrid full-network solver: `w` stations are ordered between a
    fixed entry and a fixed exit station, so both ends stay attached to the rest
    of the 26-station tour. Needs w^2 variables.
    """

    free: int          # w, the number of stations being reordered

    @property
    def num_vars(self) -> int:
        return self.free ** 2

    def var(self, station: int, position: int) -> int:
        """Variable index for station `station` at position `position` (0-based)."""
        return station * self.free + position

    def decode(self, bits) -> list:
        """Assignment -> ordering of station indices, or None if invalid."""
        positions = {}
        for station in range(self.free):
            chosen = [t for t in range(self.free) if bits[self.var(station, t)]]
            if len(chosen) != 1:
                return None
            positions[station] = chosen[0]
        if len(set(positions.values())) != self.free:
            return None
        return [s for s, _ in sorted(positions.items(), key=lambda kv: kv[1])]


def build_path_qubo(entry_cost, exit_cost, pair_cost, penalty: float):
    """QUBO for ordering w stations between a fixed entry and a fixed exit.

    `entry_cost[i]` is the cost from the entry station to station i,
    `exit_cost[i]` from station i to the exit station, and `pair_cost[i][j]`
    between two of the free stations. Same position encoding and the same
    "exactly one" penalties as the closed-tour QUBO - only the two ends differ.
    """
    w = len(entry_cost)
    encoding = PathEncoding(free=w)
    qubo = QUBO(num_vars=encoding.num_vars)

    for i in range(w):
        qubo.add_linear(encoding.var(i, 0), entry_cost[i])
        qubo.add_linear(encoding.var(i, w - 1), exit_cost[i])

    for position in range(w - 1):
        for a in range(w):
            for b in range(w):
                if a == b:
                    continue
                qubo.add_quadratic(
                    encoding.var(a, position),
                    encoding.var(b, position + 1),
                    pair_cost[a][b],
                )

    for i in range(w):
        qubo.add_exactly_one([encoding.var(i, t) for t in range(w)], penalty)
    for t in range(w):
        qubo.add_exactly_one([encoding.var(i, t) for i in range(w)], penalty)

    return qubo, encoding


def default_penalty(instance) -> float:
    """A weight big enough that violating a constraint is never worth it."""
    return max(1.0, instance.size * instance.max_distance)


def build_tsp_qubo(instance, penalty: float = None):
    """TSP instance -> (QUBO, Encoding, penalty actually used)."""
    if penalty is None:
        penalty = default_penalty(instance)

    k = instance.size
    encoding = Encoding(size=k)
    qubo = QUBO(num_vars=encoding.num_vars)

    # --- objective: the length of the closed tour -------------------------
    for station in range(1, k):
        # start -> first station
        qubo.add_linear(encoding.var(station, 1), instance.distance(0, station))
        # last station -> back to the start
        qubo.add_linear(encoding.var(station, k - 1), instance.distance(station, 0))

    for position in range(1, k - 1):
        for a in range(1, k):
            for b in range(1, k):
                if a == b:
                    continue           # a station cannot follow itself
                qubo.add_quadratic(
                    encoding.var(a, position),
                    encoding.var(b, position + 1),
                    instance.distance(a, b),
                )

    # --- constraints: the assignment must be a permutation ----------------
    for station in range(1, k):
        qubo.add_exactly_one(
            [encoding.var(station, t) for t in range(1, k)], penalty
        )
    for position in range(1, k):
        qubo.add_exactly_one(
            [encoding.var(s, position) for s in range(1, k)], penalty
        )

    return qubo, encoding, penalty
