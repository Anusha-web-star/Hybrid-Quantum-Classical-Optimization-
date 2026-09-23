"""The transmission network as an undirected weighted graph.

The CSV describes a *sparse* network: 26 stations joined by 38 lines, so most
station pairs have no direct line between them. A tour that must visit every
station therefore cannot only use direct lines.

The fix is the standard one: build the shortest-path closure. `travel_cost(a, b)`
is the length of the shortest chain of real transmission lines from `a` to `b`,
computed with Dijkstra over `Distance_km`. Every cost the solver sees is a sum
of real line lengths - no distance is invented, and no straight-line "as the crow
flies" distance is ever substituted for a missing line.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Optional

from .data_loader import Dataset


class NetworkError(Exception):
    """The network cannot support a tour (e.g. it is disconnected)."""


@dataclass
class Edge:
    """A routable link between two stations, with its dataset attributes."""

    a: str
    b: str
    distance_km: float
    voltage_kv: Optional[float] = None
    capacity_mw: Optional[float] = None
    loss_percent: Optional[float] = None
    energy_loss_mw: Optional[float] = None


class Network:
    """Undirected graph built from a `Dataset`."""

    def __init__(self, dataset: Dataset):
        self.dataset = dataset
        self.stations = dataset.stations
        self.names = dataset.station_names

        self.edges: dict = {}      # (a, b) sorted tuple -> Edge
        self.adjacency: dict = {name: {} for name in self.names}

        for connection in dataset.routable_connections:
            if connection.source == connection.destination:
                continue  # a self-loop is never part of a tour
            self._add_edge(connection)

        # Shortest-path closure, filled in lazily by `_ensure_closure`.
        self._dist: dict = {}
        self._prev: dict = {}

    # ---------------------------------------------------------------- build

    def _add_edge(self, connection) -> None:
        key = tuple(sorted((connection.source, connection.destination)))
        existing = self.edges.get(key)
        # Parallel lines between the same pair: route over the shorter one.
        if existing is not None and existing.distance_km <= connection.distance_km:
            return

        edge = Edge(
            a=key[0],
            b=key[1],
            distance_km=connection.distance_km,
            voltage_kv=connection.voltage_kv,
            capacity_mw=connection.capacity_mw,
            loss_percent=connection.loss_percent,
            energy_loss_mw=connection.energy_loss_mw,
        )
        self.edges[key] = edge
        self.adjacency[connection.source][connection.destination] = edge.distance_km
        self.adjacency[connection.destination][connection.source] = edge.distance_km

    def edge_between(self, a: str, b: str) -> Optional[Edge]:
        return self.edges.get(tuple(sorted((a, b))))

    # --------------------------------------------------------- connectivity

    def components(self) -> list:
        """Connected groups of stations, largest first."""
        unseen = set(self.names)
        groups = []
        while unseen:
            root = next(iter(unseen))
            group, stack = set(), [root]
            while stack:
                node = stack.pop()
                if node in group:
                    continue
                group.add(node)
                stack.extend(n for n in self.adjacency[node] if n not in group)
            unseen -= group
            groups.append(sorted(group))
        groups.sort(key=len, reverse=True)
        return groups

    @property
    def is_connected(self) -> bool:
        return len(self.components()) == 1

    def isolated_stations(self) -> list:
        """Stations with no routable line at all."""
        return sorted(n for n in self.names if not self.adjacency[n])

    def require_connected(self) -> None:
        """Raise a readable error if no tour over all stations can exist."""
        groups = self.components()
        if len(groups) == 1:
            return

        isolated = self.isolated_stations()
        lines = [
            f"The network is disconnected: {len(groups)} separate groups, so no "
            f"route can visit all {len(self.names)} stations and come back."
        ]
        for i, group in enumerate(groups, start=1):
            preview = ", ".join(group[:6]) + (" ..." if len(group) > 6 else "")
            lines.append(f"  group {i} ({len(group)} stations): {preview}")
        if isolated:
            lines.append(
                f"  stations with no usable connection: {', '.join(isolated)}"
            )
        lines.append(
            "Add the missing transmission line(s) to the CSV, or run Phase 1 on "
            "one group at a time with --component N."
        )
        raise NetworkError("\n".join(lines))

    def subnetwork_names(self, component_index: int) -> list:
        """Station names of one connected group (1-based index)."""
        groups = self.components()
        if not 1 <= component_index <= len(groups):
            raise NetworkError(
                f"--component {component_index} is out of range; the network "
                f"has {len(groups)} group(s)."
            )
        return groups[component_index - 1]

    # ------------------------------------------------------------- distances

    def _dijkstra(self, source: str) -> None:
        """Shortest distances and predecessors from one station."""
        dist = {source: 0.0}
        prev: dict = {}
        queue = [(0.0, source)]
        settled = set()

        while queue:
            d, node = heapq.heappop(queue)
            if node in settled:
                continue
            settled.add(node)
            for neighbour, weight in self.adjacency[node].items():
                nd = d + weight
                if nd < dist.get(neighbour, float("inf")):
                    dist[neighbour] = nd
                    prev[neighbour] = node
                    heapq.heappush(queue, (nd, neighbour))

        self._dist[source] = dist
        self._prev[source] = prev

    def _ensure_closure(self, source: str) -> None:
        if source not in self._dist:
            self._dijkstra(source)

    def travel_cost(self, a: str, b: str) -> float:
        """Shortest distance in km along real transmission lines, or infinity."""
        if a == b:
            return 0.0
        self._ensure_closure(a)
        return self._dist[a].get(b, float("inf"))

    def travel_path(self, a: str, b: str) -> list:
        """The chain of stations actually traversed from `a` to `b`."""
        if a == b:
            return [a]
        self._ensure_closure(a)
        if b not in self._dist[a]:
            return []
        path, node = [b], b
        while node != a:
            node = self._prev[a][node]
            path.append(node)
        path.reverse()
        return path

    def is_direct_line(self, a: str, b: str) -> bool:
        return b in self.adjacency.get(a, {})

    # ------------------------------------------------------------- reporting

    def summary(self) -> dict:
        groups = self.components()
        distances = [e.distance_km for e in self.edges.values()]
        return {
            "stations": len(self.names),
            "rows_in_csv": len(self.dataset.connections),
            "routable_lines": len(self.edges),
            "components": len(groups),
            "isolated": self.isolated_stations(),
            "shortest_line_km": min(distances) if distances else None,
            "longest_line_km": max(distances) if distances else None,
            "total_line_km": sum(distances),
        }
