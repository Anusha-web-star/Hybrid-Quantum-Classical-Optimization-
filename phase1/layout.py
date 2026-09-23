"""Node placement for the network map.

The dataset's real coordinates are the right starting point, but they are not
directly drawable: five power houses on the Kali river (Kaiga, Kadra, Kodasalli,
Nagjhari, Supa Dam) sit within ~15 km of each other, so at the scale of the whole
Karnataka grid their markers land on top of one another.

So the layout is geographic *first*, then relaxed:

    1. Seed every station at its true (longitude, latitude) from the CSV.
    2. Stations with no coordinates are pulled to the centroid of their
       connected neighbours instead of being parked arbitrarily.
    3. Run an anchored repulsion pass: any two markers closer than the minimum
       separation push each other apart, while a spring holds each station near
       its true position. The spring decays to zero, so overlaps always clear
       while the map keeps its geographic shape.
    4. With no usable coordinates at all, fall back to a force-directed
       (Fruchterman-Reingold) layout driven by the transmission lines.

Nothing here touches the dataset. `Layout.true_positions` keeps the original
coordinates, and any station moved to make room is drawn with a marker at its
real position so the map never misrepresents where a station is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Minimum gap between two markers, as a fraction of the map's larger span.
# Sized so the tightest real cluster (five Kali river power houses inside ~15 km)
# ends up with room for a marker, a leg number and a label between neighbours.
MIN_SEPARATION_RATIO = 0.048

# A station is reported as "displaced" once it moves this far from its true spot.
DISPLACEMENT_RATIO = 0.006

RELAX_ITERATIONS = 600
ANCHOR_STRENGTH = 0.12


@dataclass
class Layout:
    """Where to draw each station, and how that relates to the real coordinates."""

    positions: dict                     # name -> (x, y) as drawn
    true_positions: dict                # name -> (x, y) from the CSV, when known
    mode: str                           # "geographic" | "force-directed"
    min_separation: float
    displaced: set = field(default_factory=set)
    placed_without_coordinates: set = field(default_factory=set)

    @property
    def span(self) -> float:
        xs = [p[0] for p in self.positions.values()]
        ys = [p[1] for p in self.positions.values()]
        return max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0


def compute_layout(network, mode: str = "auto") -> Layout:
    """Build a readable layout. `mode` is "auto", "geographic" or "force"."""
    geo = {
        name: (station.longitude, station.latitude)
        for name, station in network.stations.items()
        if station.has_coordinates
    }

    use_geographic = mode == "geographic" or (mode == "auto" and len(geo) >= 2)
    if mode == "force" or not use_geographic:
        return _force_directed_layout(network)
    return _geographic_layout(network, geo)


# --------------------------------------------------------------- geographic


def _geographic_layout(network, geo: dict) -> Layout:
    without_coords = [n for n in network.names if n not in geo]
    seeded = dict(geo)

    if without_coords:
        seeded.update(_seed_missing(network, geo, without_coords))

    span = _span(seeded)
    min_sep = MIN_SEPARATION_RATIO * span

    # Only stations with real coordinates are anchored; the rest are free to
    # settle wherever their connections pull them.
    positions = _relax_overlaps(seeded, anchors=geo, min_sep=min_sep)

    threshold = DISPLACEMENT_RATIO * span
    displaced = {
        name for name, point in positions.items()
        if name in geo and _distance(point, geo[name]) > threshold
    }

    return Layout(
        positions=positions,
        true_positions=geo,
        mode="geographic",
        min_separation=min_sep,
        displaced=displaced,
        placed_without_coordinates=set(without_coords),
    )


def _seed_missing(network, geo: dict, missing: list) -> dict:
    """Place coordinate-less stations near the neighbours they connect to."""
    cx, cy = _centroid(geo)
    seeded = {}
    for i, name in enumerate(sorted(missing)):
        known = [geo[n] for n in network.adjacency[name] if n in geo]
        if known:
            seeded[name] = _centroid_of(known)
        else:
            # Nothing to anchor it to: put it on a ring around the map.
            angle = 2 * math.pi * i / len(missing)
            radius = _span(geo) * 0.6 if geo else 1.0
            seeded[name] = (cx + radius * math.cos(angle),
                            cy + radius * math.sin(angle))
    return seeded


def _relax_overlaps(
    seed: dict,
    anchors: dict,
    min_sep: float,
    iterations: int = RELAX_ITERATIONS,
) -> dict:
    """Push markers apart until none overlap, holding them near their anchors.

    The anchor spring decays linearly to zero, so early iterations preserve the
    geography and later ones guarantee the separation actually clears.
    """
    names = sorted(seed)
    pos = {name: [float(seed[name][0]), float(seed[name][1])] for name in names}
    count = len(names)

    for iteration in range(iterations):
        displacement = {name: [0.0, 0.0] for name in names}
        overlapping = False

        for i, a in enumerate(names):
            ax, ay = pos[a]
            for b in names[i + 1:]:
                bx, by = pos[b]
                dx, dy = ax - bx, ay - by
                distance = math.hypot(dx, dy)
                if distance >= min_sep:
                    continue
                overlapping = True
                if distance < 1e-12:
                    # Exactly coincident: split along a fixed direction so the
                    # layout stays reproducible run to run.
                    angle = 2 * math.pi * i / count
                    dx, dy, distance = math.cos(angle), math.sin(angle), 1.0
                push = (min_sep - distance) * 0.55
                ux, uy = dx / distance, dy / distance
                displacement[a][0] += ux * push
                displacement[a][1] += uy * push
                displacement[b][0] -= ux * push
                displacement[b][1] -= uy * push

        if not overlapping:
            break

        pull = ANCHOR_STRENGTH * (1.0 - iteration / iterations)
        for name in names:
            pos[name][0] += displacement[name][0]
            pos[name][1] += displacement[name][1]
            anchor = anchors.get(name)
            if anchor is not None and pull > 0.0:
                pos[name][0] += pull * (anchor[0] - pos[name][0])
                pos[name][1] += pull * (anchor[1] - pos[name][1])

    return {name: (point[0], point[1]) for name, point in pos.items()}


# ------------------------------------------------------------ force-directed


def _force_directed_layout(network) -> Layout:
    """Fruchterman-Reingold over the transmission lines. Used with no coordinates."""
    names = sorted(network.names)
    count = len(names)
    area = 1.0
    k = math.sqrt(area / count) if count else 1.0

    # Deterministic start: evenly spaced on a circle.
    pos = {
        name: [0.5 * math.cos(2 * math.pi * i / count),
               0.5 * math.sin(2 * math.pi * i / count)]
        for i, name in enumerate(names)
    }

    temperature = 0.15
    iterations = 500
    for _ in range(iterations):
        displacement = {name: [0.0, 0.0] for name in names}

        for i, a in enumerate(names):
            for b in names[i + 1:]:
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                distance = max(math.hypot(dx, dy), 1e-6)
                force = (k * k) / distance          # repulsion
                ux, uy = dx / distance, dy / distance
                displacement[a][0] += ux * force
                displacement[a][1] += uy * force
                displacement[b][0] -= ux * force
                displacement[b][1] -= uy * force

        for edge in network.edges.values():
            dx = pos[edge.a][0] - pos[edge.b][0]
            dy = pos[edge.a][1] - pos[edge.b][1]
            distance = max(math.hypot(dx, dy), 1e-6)
            force = (distance * distance) / k        # attraction along lines
            ux, uy = dx / distance, dy / distance
            displacement[edge.a][0] -= ux * force
            displacement[edge.a][1] -= uy * force
            displacement[edge.b][0] += ux * force
            displacement[edge.b][1] += uy * force

        for name in names:
            dx, dy = displacement[name]
            magnitude = max(math.hypot(dx, dy), 1e-9)
            step = min(magnitude, temperature)
            pos[name][0] += dx / magnitude * step
            pos[name][1] += dy / magnitude * step

        temperature *= 0.985

    positions = {name: (p[0], p[1]) for name, p in pos.items()}
    span = _span(positions)
    min_sep = MIN_SEPARATION_RATIO * span
    positions = _relax_overlaps(positions, anchors={}, min_sep=min_sep)

    return Layout(
        positions=positions,
        true_positions={},
        mode="force-directed",
        min_separation=min_sep,
        displaced=set(),
        placed_without_coordinates=set(names),
    )


# ------------------------------------------------------------------ helpers


def _span(positions: dict) -> float:
    if not positions:
        return 1.0
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    return max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0


def _centroid(positions: dict):
    return _centroid_of(list(positions.values()))


def _centroid_of(points: list):
    if not points:
        return (0.0, 0.0)
    return (sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points))


def _distance(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
