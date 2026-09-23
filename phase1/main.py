"""Phase 1 command-line entry point.

    python run_phase1.py --list
    python run_phase1.py --start "Mysuru Substation"
    python run_phase1.py                      (asks which station to start from)

A normal run prints a concise summary. `--verbose` adds the dataset report and
the per-leg breakdown for debugging.
"""

from __future__ import annotations

import argparse
import sys

from .data_loader import DatasetError, load_dataset
from .network import Network, NetworkError
from .nn_tsp import SolverError, resolve_station, solve
from .visualize import plot_route

RULE = "=" * 60


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_phase1.py",
        description="Phase 1 - dataset load + classical Nearest Neighbour TSP.",
    )
    parser.add_argument("--data", help="Path to the CSV (default: the one in data/).")
    parser.add_argument("--start", help="Starting station name.")
    parser.add_argument("--list", action="store_true",
                        help="List every station in the dataset and exit.")
    parser.add_argument("--component", type=int, metavar="N",
                        help="Route within connected group N only "
                             "(for disconnected networks).")
    parser.add_argument("--output", default="outputs/nn_route.png",
                        help="Where to save the network map.")
    parser.add_argument("--no-plot", action="store_true",
                        help="Skip the visualization.")
    parser.add_argument("--no-labels", action="store_true",
                        help="Hide station names on the map.")
    parser.add_argument("--layout", choices=("auto", "geographic", "force"),
                        default="auto",
                        help="Map layout: 'geographic' uses the CSV coordinates "
                             "(spaced out so markers do not overlap), 'force' "
                             "uses a force-directed layout, 'auto' picks "
                             "geographic when coordinates exist (default).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Diagnostics: full dataset report and per-leg table.")
    return parser


def connectivity_label(summary) -> str:
    """One phrase for whether the network hangs together."""
    groups = summary["components"]
    if groups == 1:
        return "connected"
    return f"disconnected ({groups} groups)"


def validate(result, pool) -> list:
    """Check the tour really is a TSP tour. Returns (label, passed) pairs."""
    closed = result.closed_route
    return [
        ("valid TSP tour (returns to start)",
         len(closed) > 1 and closed[0] == closed[-1]),
        (f"all {len(pool)} stations visited exactly once",
         sorted(result.order) == sorted(pool)),
    ]


def print_summary(dataset, network, result, pool) -> bool:
    """The concise Phase 1 report. Returns True when every check passed."""
    summary = network.summary()

    print(RULE)
    print("GRIDOPT - PHASE 1 : Nearest Neighbour TSP")
    print(RULE)
    print()
    print(f"  Stations           : {summary['stations']}")
    print(f"  Transmission lines : {summary['routable_lines']}")
    print(f"  Connectivity       : {connectivity_label(summary)}")
    print(f"  Starting station   : {result.start}")
    if dataset.warnings:
        print(f"  Warnings           : {len(dataset.warnings)} "
              f"(run with --verbose for details)")

    print("\n  Route:")
    print("    " + "\n     -> ".join(_wrap_route(result.closed_route)))

    print(f"\n  Total distance     : {result.total_distance_km:,.3f} km")
    print(f"  Execution time     : {result.execution_time_s * 1000:.3f} ms")

    print()
    checks = validate(result, pool)
    for label, passed in checks:
        mark = "ok" if passed else "FAIL"
        print(f"  [{mark}] {label}")
    print(RULE)
    print()
    return all(passed for _, passed in checks)


def print_dataset_report(dataset, network) -> None:
    """Diagnostics: what the loader and the graph builder saw."""
    summary = network.summary()
    print(RULE)
    print("DATASET (diagnostics)")
    print(RULE)
    print(f"  File               : {dataset.path}")
    print(f"  Rows in CSV        : {summary['rows_in_csv']}")
    print(f"  Stations           : {summary['stations']}")
    print(f"  Routable lines     : {summary['routable_lines']}")
    print(f"  Connected groups   : {summary['components']}"
          f"{'  (fully connected)' if summary['components'] == 1 else ''}")
    if summary["shortest_line_km"] is not None:
        print(f"  Line length range  : {summary['shortest_line_km']:.3f} km "
              f"- {summary['longest_line_km']:.3f} km")
        print(f"  Total line length  : {summary['total_line_km']:,.3f} km")
    if summary["isolated"]:
        print(f"  Isolated stations  : {', '.join(summary['isolated'])}")

    print("\n  Attributes carried through for the later energy-loss phase:")
    for name, (present, total) in dataset.attribute_coverage().items():
        pct = (present / total * 100) if total else 0.0
        print(f"    {name:<16} {present}/{total} rows ({pct:.0f}%)")

    if dataset.warnings:
        print(f"\n  Warnings ({len(dataset.warnings)}):")
        for warning in dataset.warnings:
            print(f"    - {warning}")
    else:
        print("\n  Warnings: none - every row parsed cleanly.")
    print()


def print_legs(result) -> None:
    """Diagnostics: the per-leg breakdown behind the total."""
    print(RULE)
    print("LEGS (diagnostics)")
    print(RULE)
    print(f"  Direct-line legs   : {result.direct_legs}/{len(result.legs)} "
          f"(the rest route through intermediate stations)")
    print()
    print(f"    {'#':>3}  {'from':<38} {'to':<38} {'km':>10}  via")
    for leg in result.legs:
        via = " > ".join(leg.via) if leg.via else "-"
        print(f"    {leg.step:>3}  {leg.origin:<38} {leg.destination:<38} "
              f"{leg.distance_km:>10.3f}  {via}")
    print(f"    {'':>3}  {'TOTAL':<38} {'':<38} "
          f"{result.total_distance_km:>10.3f}")
    print()


def print_stations(network) -> None:
    print(RULE)
    print(f"STATIONS ({len(network.names)})")
    print(RULE)
    width = max(len(n) for n in network.names)
    for i, name in enumerate(network.names, start=1):
        station = network.stations[name]
        coords = (
            f"({station.latitude:.4f}, {station.longitude:.4f})"
            if station.has_coordinates else "(no coordinates)"
        )
        degree = len(network.adjacency[name])
        print(f"  {i:>2}. {name:<{width}}  {coords:<22} "
              f"{station.type_label:<12} {degree} line(s)")
    print()


def choose_start(network) -> str:
    """Ask the user which station to start from."""
    print_stations(network)
    prompt = "Choose a starting station (name or number): "
    while True:
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(1)
        if not answer:
            continue
        if answer.isdigit():
            index = int(answer)
            if 1 <= index <= len(network.names):
                return network.names[index - 1]
            print(f"  Enter a number between 1 and {len(network.names)}.")
            continue
        try:
            return resolve_station(network, answer)
        except SolverError as exc:
            print(f"  {exc}")


def _wrap_route(route: list) -> list:
    """Break the route into readable chunks for the console."""
    return [" -> ".join(route[i:i + 3]) for i in range(0, len(route), 3)]


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        dataset = load_dataset(args.data)
    except DatasetError as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2

    network = Network(dataset)
    if args.verbose:
        print_dataset_report(dataset, network)

    if args.list:
        print_stations(network)
        return 0

    # Requirement 11: a tour over all stations needs a connected network.
    try:
        if args.component is not None:
            pool = network.subnetwork_names(args.component)
            print(f"Routing within connected group {args.component} "
                  f"({len(pool)} stations).\n")
        else:
            network.require_connected()
            pool = network.names
    except NetworkError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 3

    start = args.start or choose_start(network)

    try:
        result = solve(network, start, stations=pool)
    except SolverError as exc:
        print(f"Invalid starting station: {exc}", file=sys.stderr)
        return 4
    except NetworkError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 3

    valid = print_summary(dataset, network, result, pool)
    if args.verbose:
        print_legs(result)

    if not args.no_plot:
        try:
            path = plot_route(
                network, result,
                output_path=args.output,
                show_labels=not args.no_labels,
                layout_mode=args.layout,
            )
            print(f"  Network map saved to: {path}\n")
        except Exception as exc:  # a plotting failure must not lose the result
            print(f"  Visualization failed ({exc}); the route above is "
                  f"still valid.\n", file=sys.stderr)

    return 0 if valid else 5


if __name__ == "__main__":
    raise SystemExit(main())
