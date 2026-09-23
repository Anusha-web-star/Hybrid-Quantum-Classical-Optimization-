"""Network map: the grid, the Nearest Neighbour route, and the starting station.

Layers, back to front:

    1. grey     every transmission line in the dataset
    2. blue     the Nearest Neighbour route, drawn along the lines it actually
                uses, with each leg numbered in visiting order
    3. dark     every station
    4. red star the starting station
    5. labels   every station name, placed to avoid other markers and labels

Positions come from `phase1.layout`: real coordinates, relaxed just enough that
no two markers overlap. Where a station had to be nudged, a hollow ring marks its
true coordinates and a hairline joins the two, so the map stays honest about the
data.
"""

from __future__ import annotations

import itertools
import math
import os
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # write a file; no interactive backend needed
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from .layout import compute_layout  # noqa: E402

GRID_COLOUR = "#aebac4"
ROUTE_COLOUR = "#1f77b4"
START_COLOUR = "#d62728"
STATION_COLOUR = "#2f3e46"
TRUE_POSITION_COLOUR = "#8d99a6"

FIGURE_SIZE = (22.0, 17.0)
LABEL_FONT_SIZE = 8.0

# Label candidates: (dx, dy) unit directions, in preference order.
_DIRECTIONS = [
    (1.0, 0.35), (1.0, -0.35), (-1.0, 0.35), (-1.0, -0.35),
    (1.0, 0.0), (-1.0, 0.0),
    (0.35, 1.0), (0.35, -1.0), (-0.35, 1.0), (-0.35, -1.0),
    (0.0, 1.0), (0.0, -1.0),
]

# How far a label may sit from its station, in typographic points. A crowded
# station falls through to a further ring and gets a leader line.
_RADII_PT = [11.0, 24.0, 38.0, 54.0, 72.0, 94.0, 118.0, 146.0]

# Radius of a leg-number badge, in points.
_BADGE_RADIUS_PT = 9.5

# Below this cost a candidate has no collisions worth escaping.
_CLEAN_COST = 16.0


# --------------------------------------------------------------- label boxes


def _text_size(text: str, font_size: float, scale_x: float, scale_y: float):
    """Approximate a rendered label's width and height in data units."""
    width_pt = len(text) * font_size * 0.56 + 3.0
    height_pt = font_size * 1.35
    return width_pt * scale_x, height_pt * scale_y


def _box_for(anchor, direction, width, height):
    """Bounding box of a label anchored beside its station."""
    x, y = anchor
    if direction[0] > 0.2:
        x0, x1 = x, x + width
    elif direction[0] < -0.2:
        x0, x1 = x - width, x
    else:
        x0, x1 = x - width / 2, x + width / 2
    if direction[1] > 0.2:
        y0, y1 = y, y + height
    elif direction[1] < -0.2:
        y0, y1 = y - height, y
    else:
        y0, y1 = y - height / 2, y + height / 2
    return (x0, y0, x1, y1)


def _overlap_area(a, b) -> float:
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return dx * dy if dx > 0 and dy > 0 else 0.0


def _point_in_box(point, box) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _place_labels(
    names, positions, font_size, scale_x, scale_y, node_radius, limits,
    obstacles=(),
):
    """Choose a position for every label that clears markers and other labels.

    Greedy: the most crowded stations pick first, since they have the fewest
    workable options. Each candidate is scored on whether it covers a station
    marker, overlaps a label already placed or a leg-number badge, or falls off
    the axes; ties break toward the closest ring and the most natural direction.

    `obstacles` are boxes already occupied by other chrome (the leg numbers).

    Returns name -> (anchor, direction, radius_index).
    """
    points = [positions[n] for n in names]
    xmin, xmax, ymin, ymax = limits
    obstacles = list(obstacles)

    def crowding(name):
        x, y = positions[name]
        reach = node_radius * 8
        return -sum(
            1 for px, py in points
            if abs(px - x) < reach and abs(py - y) < reach
        )

    placements = {}
    taken_boxes = []

    for name in sorted(names, key=lambda n: (crowding(n), n)):
        x, y = positions[name]
        width, height = _text_size(name, font_size, scale_x, scale_y)
        area = width * height

        best = None
        for radius_index, radius_pt in enumerate(_RADII_PT):
            for direction_index, (ux, uy) in enumerate(_DIRECTIONS):
                anchor = (x + ux * radius_pt * scale_x,
                          y + uy * radius_pt * scale_y)
                box = _box_for(anchor, (ux, uy), width, height)

                covered = sum(1 for point in points if _point_in_box(point, box))
                overlap = sum(
                    _overlap_area(box, other)
                    for other in taken_boxes + obstacles
                )
                outside = (
                    box[0] < xmin or box[2] > xmax or box[1] < ymin or box[3] > ymax
                )

                cost = (
                    covered * 1000.0
                    + (overlap / area) * 900.0
                    + (400.0 if outside else 0.0)
                    + radius_index * 14.0
                    + direction_index * 1.0
                )
                if best is None or cost < best[0]:
                    best = (cost, anchor, (ux, uy), radius_index, box)

            if best[0] < _CLEAN_COST:
                break  # a clean spot on this ring; no need to push further out

        _, anchor, direction, radius_index, box = best
        placements[name] = (anchor, direction, radius_index)
        taken_boxes.append(box)

    return placements


# ------------------------------------------------------------------ helpers


def _polyline_midpoint(points):
    """Point half way along a polyline, by arc length."""
    if len(points) == 1:
        return points[0]
    if len(points) == 0:
        return (0.0, 0.0)
    lengths = [
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])
    ]
    total = sum(lengths)
    if total <= 0:
        return points[0]
    target, walked = total / 2, 0.0
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if walked + length >= target:
            t = (target - walked) / length if length else 0.0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        walked += length
    return points[-1]


def _measure(fig, ax, label_texts, badge_texts, node_points, marker_radius_pt):
    """Measure what was actually rendered, in pixels.

    Checks the drawing rather than the plan: matplotlib is asked for the real
    bounding box of every label after layout, so "nothing overlaps" is a
    measurement, not an assumption.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    def box_of(text):
        patch = text.get_bbox_patch()
        source = patch if patch is not None else text
        bbox = source.get_window_extent(renderer)
        return (bbox.x0, bbox.y0, bbox.x1, bbox.y1)

    label_boxes = {name: box_of(text) for name, text in label_texts.items()}
    badge_boxes = [box_of(text) for text in badge_texts]
    pixels = {name: tuple(ax.transData.transform(point))
              for name, point in node_points.items()}

    marker_px = marker_radius_pt * fig.dpi / 72.0

    names = sorted(label_boxes)
    label_collisions = [
        (a, b) for a, b in itertools.combinations(names, 2)
        if _overlap_area(label_boxes[a], label_boxes[b]) > 1.0
    ]
    labels_over_badges = sum(
        1 for box in label_boxes.values()
        for badge in badge_boxes
        if _overlap_area(box, badge) > 1.0
    )
    labels_over_nodes = [
        (name, other)
        for name, box in label_boxes.items()
        for other, point in pixels.items()
        if _overlap_area(box, (point[0] - marker_px, point[1] - marker_px,
                               point[0] + marker_px, point[1] + marker_px)) > 1.0
    ]

    node_names = sorted(pixels)
    separations = [
        math.dist(pixels[a], pixels[b])
        for a, b in itertools.combinations(node_names, 2)
    ]

    return {
        "stations_drawn": len(pixels),
        "labels_drawn": len(label_boxes),
        "label_collisions": label_collisions,
        "labels_over_nodes": labels_over_nodes,
        "labels_over_badges": labels_over_badges,
        "min_node_separation_px": min(separations) if separations else 0.0,
        "node_marker_diameter_px": 2 * marker_px,
        "figure_size_px": (fig.get_size_inches()[0] * fig.dpi,
                           fig.get_size_inches()[1] * fig.dpi),
    }


# -------------------------------------------------------------------- plot


def plot_route(
    network,
    result,
    output_path: str = "outputs/nn_route.png",
    show_labels: bool = True,
    layout_mode: str = "auto",
    title: Optional[str] = None,
    diagnostics: Optional[dict] = None,
    route_label: str = "Nearest Neighbour route (legs numbered)",
) -> str:
    """Render the network with the tour overlaid and save it as a PNG.

    Pass a dict as `diagnostics` to have it filled with measurements of the
    rendered figure (label collisions, marker separation).

    `route_label` names the route in the legend. It defaults to the Nearest
    Neighbour wording, so Phase 1 renders exactly as before; Phase 2 passes its
    own text so a hybrid-QAOA map is never labelled as a Nearest Neighbour one.
    """
    layout = compute_layout(network, mode=layout_mode)
    pos = layout.positions
    on_route = set(result.order)

    fig, ax = plt.subplots(figsize=FIGURE_SIZE)

    # --- layer 1: the network itself ------------------------------------
    for edge in network.edges.values():
        x1, y1 = pos[edge.a]
        x2, y2 = pos[edge.b]
        ax.plot([x1, x2], [y1, y2], color=GRID_COLOUR, linewidth=1.4,
                zorder=1, solid_capstyle="round")

    # --- layer 2: the route ---------------------------------------------
    for leg in result.legs:
        points = [pos[n] for n in leg.path]
        ax.plot([p[0] for p in points], [p[1] for p in points],
                color=ROUTE_COLOUR, linewidth=3.2, alpha=0.85,
                zorder=2, solid_capstyle="round", solid_joinstyle="round")

    # --- layer 3: stations ----------------------------------------------
    for name in network.names:
        x, y = pos[name]
        if name == result.start:
            continue
        ax.scatter([x], [y], s=110 if name in on_route else 70,
                   c=STATION_COLOUR, edgecolors="white", linewidths=1.1, zorder=4)

    sx, sy = pos[result.start]
    ax.scatter([sx], [sy], s=760, c=START_COLOUR, marker="*",
               edgecolors="white", linewidths=1.6, zorder=7)

    # --- true coordinates of any station nudged apart --------------------
    for name in sorted(layout.displaced):
        tx, ty = layout.true_positions[name]
        px, py = pos[name]
        ax.plot([tx, px], [ty, py], color=TRUE_POSITION_COLOUR, linewidth=0.8,
                linestyle=":", zorder=3)
        ax.scatter([tx], [ty], s=26, facecolors="none",
                   edgecolors=TRUE_POSITION_COLOUR, linewidths=0.9, zorder=3)

    # Axis limits must be final before label geometry is computed.
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    pad_x = (max(xs) - min(xs)) * 0.14 or 1.0
    pad_y = (max(ys) - min(ys)) * 0.08 or 1.0
    ax.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
    ax.set_ylim(min(ys) - pad_y, max(ys) + pad_y)
    # The axes fill the figure rather than locking to a 1:1 degree ratio: station
    # names are wide and horizontal, and the grid spans more latitude than
    # longitude, so an equal aspect would waste the width the labels need.
    ax.set_aspect("auto")

    # Point-to-data scaling, needed to size the leg badges and the labels.
    fig.canvas.draw()  # fixes the transform so point->data scaling is real
    extent = ax.get_window_extent()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    px_per_pt = fig.dpi / 72.0
    scale_x = (x1 - x0) / extent.width * px_per_pt
    scale_y = (y1 - y0) / extent.height * px_per_pt
    node_radius = 7.0 * scale_x  # marker radius in data units

    # --- leg numbers, on the line rather than on a station ---------------
    badge_boxes = []
    badge_texts = []
    for leg in result.legs:
        mx, my = _polyline_midpoint([pos[n] for n in leg.path])
        badge_texts.append(ax.annotate(
            str(leg.step), (mx, my), fontsize=8, color="white", zorder=6,
            ha="center", va="center",
            bbox=dict(boxstyle="circle,pad=0.22", fc=ROUTE_COLOUR, ec="white",
                      linewidth=0.7),
        ))
        rx = _BADGE_RADIUS_PT * scale_x
        ry = _BADGE_RADIUS_PT * scale_y
        badge_boxes.append((mx - rx, my - ry, mx + rx, my + ry))

    # --- layer 5: labels -------------------------------------------------
    label_texts = {}
    if show_labels:
        placements = _place_labels(
            network.names, pos, LABEL_FONT_SIZE, scale_x, scale_y, node_radius,
            limits=(x0, x1, y0, y1),
            obstacles=badge_boxes,
        )

        for name, (anchor, direction, radius_index) in placements.items():
            is_start = name == result.start
            ha = "left" if direction[0] > 0.2 else (
                "right" if direction[0] < -0.2 else "center")
            va = "bottom" if direction[1] > 0.2 else (
                "top" if direction[1] < -0.2 else "center")

            if radius_index > 0:  # label pushed away: draw a leader line
                ax.plot([pos[name][0], anchor[0]], [pos[name][1], anchor[1]],
                        color="#9aa7b1", linewidth=0.7, zorder=5)

            label_texts[name] = ax.text(
                anchor[0], anchor[1], name,
                fontsize=LABEL_FONT_SIZE + (1.0 if is_start else 0.0),
                ha=ha, va=va, zorder=8,
                color=START_COLOUR if is_start else "#1c2529",
                fontweight="bold" if is_start else "normal",
                bbox=dict(boxstyle="round,pad=0.22", fc="white",
                          ec=START_COLOUR if is_start else "#d6dde2",
                          linewidth=1.0 if is_start else 0.5, alpha=0.92),
            )

    # --- chrome ----------------------------------------------------------
    ax.set_title(
        title
        or (
            f"Nearest Neighbour TSP route - start: {result.start}\n"
            f"{result.stations_visited} stations, "
            f"{result.total_distance_km:,.2f} km, "
            f"{result.execution_time_s * 1000:.2f} ms   "
            f"({layout.mode} layout)"
        ),
        fontsize=15,
        pad=14,
    )
    ax.set_xlabel("Longitude" if layout.mode == "geographic" else "x")
    ax.set_ylabel("Latitude" if layout.mode == "geographic" else "y")
    ax.grid(True, linestyle=":", alpha=0.3)

    handles = [
        Line2D([], [], color=GRID_COLOUR, lw=1.8, label="Transmission line"),
        Line2D([], [], color=ROUTE_COLOUR, lw=3.2,
               label=route_label),
        Line2D([], [], color=START_COLOUR, marker="*", lw=0, markersize=19,
               label=f"Start: {result.start}"),
        Line2D([], [], color=STATION_COLOUR, marker="o", lw=0, markersize=8,
               label="Station"),
    ]
    if layout.displaced:
        handles.append(
            Line2D([], [], color=TRUE_POSITION_COLOUR, marker="o", lw=0.8,
                   linestyle=":", markersize=7, markerfacecolor="none",
                   label=f"True coordinates ({len(layout.displaced)} markers "
                         f"spaced out for legibility)")
        )
    ax.legend(handles=handles, loc="upper left", fontsize=10, framealpha=0.95)

    fig.tight_layout()

    if diagnostics is not None:
        diagnostics.update(
            _measure(fig, ax, label_texts, badge_texts, pos, marker_radius_pt=7.0)
        )
        diagnostics["layout_mode"] = layout.mode
        diagnostics["displaced_stations"] = sorted(layout.displaced)

    directory = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(directory, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path
