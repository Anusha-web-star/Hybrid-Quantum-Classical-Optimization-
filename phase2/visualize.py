"""Full-network maps for the classical and hybrid-quantum routes.

Both maps are drawn by Phase 1's renderer (`phase1.visualize.plot_route`), which
is imported read-only and not modified. That buys three things:

  * the same geographic, overlap-free layout quality already tuned in Phase 1,
    including the hollow rings that mark the true coordinates of nudged markers;
  * identical station coordinates in both maps - `phase1.layout.compute_layout`
    is deterministic for a given network, so the two routes can be compared
    visually without any positional drift;
  * one renderer to maintain instead of two.

The comparison figure composes the two rendered PNGs side by side and adds a
statistics panel, so it cannot disagree with the individual maps.
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from phase1.layout import compute_layout  # noqa: E402
from phase1.visualize import plot_route  # noqa: E402

NN_TITLE = "Classical Nearest Neighbour - full network"
QAOA_TITLE = "Hybrid quantum-classical (QAOA) - full network"


def same_layout(network, mode: str = "auto") -> bool:
    """True when the layout is reproducible, i.e. both maps will align."""
    first = compute_layout(network, mode=mode).positions
    second = compute_layout(network, mode=mode).positions
    return first == second


NN_LEGEND = "Nearest Neighbour route (legs numbered)"
QAOA_LEGEND = "Hybrid QAOA route (legs numbered)"


def render_route_map(network, result, output_path: str, title: str,
                     show_labels: bool = True, layout_mode: str = "auto",
                     route_label: str = NN_LEGEND) -> str:
    """Draw one full-network route map with Phase 1's renderer.

    `route_label` keeps the legend honest: a hybrid-QAOA map must not be
    labelled as a Nearest Neighbour route.
    """
    return plot_route(
        network, result,
        output_path=output_path,
        show_labels=show_labels,
        layout_mode=layout_mode,
        title=title,
        route_label=route_label,
    )


def render_comparison(nn_png: str, qaoa_png: str, comparison,
                      output_path: str = "outputs/nn_vs_qaoa_comparison.png") -> str:
    """Compose the two maps side by side with a statistics panel beneath."""
    folder = os.path.dirname(output_path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    left = plt.imread(nn_png)
    right = plt.imread(qaoa_png)

    fig = plt.figure(figsize=(26.0, 12.0))
    grid = fig.add_gridspec(2, 2, height_ratios=[7.0, 2.0], hspace=0.04,
                            wspace=0.02)

    for column, (image, heading) in enumerate(
        ((left, NN_TITLE), (right, QAOA_TITLE))
    ):
        ax = fig.add_subplot(grid[0, column])
        ax.imshow(image)
        ax.set_title(heading, fontsize=15, fontweight="bold", pad=10)
        ax.axis("off")

    panel = fig.add_subplot(grid[1, :])
    panel.axis("off")
    _draw_stats(panel, comparison)

    fig.savefig(output_path, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def _draw_stats(ax, comparison) -> None:
    """The comparison table, drawn as text so it travels with the image."""
    ax.add_patch(Rectangle((0.0, 0.0), 1.0, 1.0, transform=ax.transAxes,
                           facecolor="#f4f6f8", edgecolor="#c9d2da"))

    rows = comparison.table_rows()
    columns = ["", "Classical NN", "Hybrid QAOA"]
    x_positions = [0.035, 0.42, 0.68]

    for x, heading in zip(x_positions, columns):
        ax.text(x, 0.88, heading, transform=ax.transAxes, fontsize=12,
                fontweight="bold", va="top")

    y = 0.72
    for label, classical, quantum in rows:
        ax.text(x_positions[0], y, label, transform=ax.transAxes, fontsize=11,
                va="top", color="#33414d")
        ax.text(x_positions[1], y, classical, transform=ax.transAxes,
                fontsize=11, va="top", family="monospace")
        ax.text(x_positions[2], y, quantum, transform=ax.transAxes,
                fontsize=11, va="top", family="monospace")
        y -= 0.115

    ax.text(0.035, 0.055, comparison.framing_note(), transform=ax.transAxes,
            fontsize=10, va="bottom", color="#5a6672", style="italic")
