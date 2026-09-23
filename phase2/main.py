"""Phase 2 command-line entry point.

    python run_phase2.py                      the whole comparison, one command
    python run_phase2.py --start "Mysuru Substation"
    python run_phase2.py --window 4           faster, slightly longer tour
    python run_phase2.py --subset --mode ibm  one QAOA subproblem on hardware

By default this runs the COMPLETE Phase 2 workflow on the full 26-station
network: pick a starting station, solve it classically with Phase 1's Nearest
Neighbour, solve it again with the hybrid QAOA reoptimizer, validate both
26-station tours, compare them, and write the three maps.

`--subset` is the separate single-instance mode: one small QAOA TSP solved end
to end, which is what `--mode ibm` sends to real hardware. That mode is a
*subproblem* demonstration - it is never the full-network answer.

A normal run prints a concise summary. `--verbose` adds the pipeline detail.
"""

from __future__ import annotations

import argparse
import sys

from phase1.data_loader import DatasetError, load_dataset
from phase1.main import choose_start
from phase1.network import Network, NetworkError
from phase1.nn_tsp import SolverError, resolve_station

from .backends import BackendError, make_runner
from .credentials import (ENV_FILE, TOKEN_VAR, credential_status,
                          env_file_present, gitignore_covers_env)
from .instance import build_instance
from .qaoa import run_qaoa
from .reference import brute_force_optimum, nearest_neighbour

RULE = "=" * 60


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_phase2.py",
        description="Phase 2 - quantum QAOA TSP over the Phase 1 dataset.",
    )
    parser.add_argument("--data", help="Path to the CSV (default: the one in data/).")
    parser.add_argument("--start", help="Starting station name.")
    parser.add_argument("--stations",
                        help="Comma-separated station names to use as the "
                             "instance (overrides --size).")
    parser.add_argument("-k", "--size", type=int, default=5,
                        help="Stations in the QAOA instance (default: 5). "
                             "Needs (k-1)^2 qubits.")
    parser.add_argument("--mode", choices=("simulator", "ibm"), default="simulator",
                        help="Where the circuits run (default: simulator).")

    qaoa = parser.add_argument_group("QAOA")
    qaoa.add_argument("--reps", type=int, default=2,
                      help="QAOA depth p (default: 2).")
    qaoa.add_argument("--shots", type=int, default=2048,
                      help="Shots per circuit run (default: 2048).")
    qaoa.add_argument("--maxiter", type=int, default=120,
                      help="COBYLA iterations per restart (default: 120).")
    qaoa.add_argument("--restarts", type=int, default=3,
                      help="Random restarts of the optimizer (default: 3).")
    qaoa.add_argument("--seed", type=int, default=7,
                      help="Seed for the sampler and the angle initialisation.")
    qaoa.add_argument("--penalty", type=float,
                      help="QUBO constraint penalty (default: k * longest leg).")
    qaoa.add_argument("--cvar", type=float, default=0.25, metavar="ALPHA",
                      help="CVaR tail fraction the optimizer minimises "
                           "(default: 0.25; use 1.0 for the plain mean).")
    qaoa.add_argument("--max-qubits", type=int, default=20,
                      help="Refuse instances larger than this (default: 20).")

    ibm = parser.add_argument_group("IBM Quantum (--mode ibm)")
    ibm.add_argument("--ibm-backend",
                     help="Device name (default: IBM_QUANTUM_BACKEND, else the "
                          "least busy operational device).")
    ibm.add_argument("--ibm-strategy", choices=("final-only", "full"),
                     default="final-only",
                     help="'final-only' trains the angles on the simulator and "
                          "sends one job to hardware (default); 'full' runs "
                          "every optimizer iteration on hardware.")
    ibm.add_argument("--ibm-shots", type=int,
                     help="Shots for the hardware job (default: --shots).")
    ibm.add_argument("--check-ibm", action="store_true",
                     help="Report whether the IBM credentials are configured, "
                          "then exit. Contacts nothing and runs no job.")

    full = parser.add_argument_group(
        "Full-network hybrid (--full): QAOA inside a 26-station reoptimization"
    )
    full.add_argument("--full", action="store_true",
                      help="Explicitly request the full-network workflow. It is "
                           "already the default; kept so existing commands and "
                           "docs keep working.")
    full.add_argument("--window", type=int, default=4, metavar="W",
                      help="Free stations per QAOA subproblem (default: 4 -> "
                           "16 qubits, ~1 min for the whole workflow). "
                           "--window 5 (25 qubits) finds shorter tours but "
                           "takes ~90 min on the simulator.")
    full.add_argument("--sweeps", type=int, default=8,
                      help="Maximum reoptimization sweeps (default: 8). A sweep "
                           "that improves nothing ends the search, so this is a "
                           "cap, not a cost.")
    full.add_argument("--no-prune", action="store_true",
                      help="Disable don't-look-bits pruning (slower, same "
                           "result).")
    full.add_argument("--outputs", default="outputs",
                      help="Folder for the generated maps (default: outputs).")
    full.add_argument("--hybrid-shots", type=int, default=2048,
                      help="Shots per subproblem circuit (default: 2048). Raise "
                           "to 4096 with --window 5: only 120 of 33.5M "
                           "bitstrings are valid orderings at 25 qubits.")
    full.add_argument("--hybrid-maxiter", type=int, default=20,
                      help="COBYLA iterations per subproblem (default: 15). "
                           "Subproblems are small; the subset mode's heavier "
                           "--maxiter is not needed here.")
    full.add_argument("--hybrid-restarts", type=int, default=1,
                      help="Optimizer restarts per subproblem (default: 1).")
    full.add_argument("--layout", choices=("auto", "geographic", "force"),
                      default="auto",
                      help="Map layout, as in Phase 1 (default: auto).")
    full.add_argument("--no-labels", action="store_true",
                      help="Hide station names on the generated maps.")

    parser.add_argument("--subset", action="store_true",
                        help="Single-instance mode: solve ONE small QAOA TSP "
                             "end to end instead of the full network. This is "
                             "the mode --mode ibm sends to hardware, and it is "
                             "a subproblem demonstration, never the "
                             "full-network result.")
    parser.add_argument("--no-compare", action="store_true",
                        help="Subset mode only: skip the Nearest Neighbour / "
                             "exact-optimum comparison.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Diagnostics: full routes, per-check validation, "
                             "the comparison table, QAOA configuration and "
                             "sweep-by-sweep progress. A normal run prints "
                             "only the results.")
    return parser


def print_summary(dataset, instance, result) -> None:
    print(RULE)
    print("GRIDOPT - PHASE 2 : Quantum QAOA (approximate optimization)")
    print(RULE)
    print()
    print(f"  Execution mode     : {result.mode}")
    print(f"  Backend            : {result.backend_description}")
    if result.job_ids:
        shown = ", ".join(result.job_ids[-3:])
        more = f" (+{len(result.job_ids) - 3} earlier)" if len(result.job_ids) > 3 else ""
        print(f"  Job ID(s)          : {shown}{more}")
        print(f"  Job status         : {result.job_status}")
    print(f"  Dataset            : {dataset.path}")
    print(f"  Full network       : {instance.total_stations} stations, "
          f"{instance.total_lines} transmission lines (unchanged)")
    print(f"  QAOA instance      : {instance.size} of "
          f"{instance.total_stations} stations, taken from that same CSV")
    print(f"  Selection rule     : {instance.selection}")
    print(f"  Starting station   : {instance.start}")
    print(f"  Qubits             : {result.num_qubits} "
          f"(QAOA depth p={result.reps}, {2 * result.reps} angles)")
    print(f"  Shots per run      : {result.shots}")

    print("\n  Best valid route found by QAOA:")
    if result.route:
        print("    " + "\n     -> ".join(_wrap_route(result.route)))
    else:
        print("    none - no sampled bitstring decoded to a valid tour")

    if result.route:
        print(f"\n  Total distance     : {result.total_distance_km:,.3f} km")
    print(f"  Execution time     : {result.execution_time_s:.3f} s")

    print()
    for label, passed in result.checks:
        print(f"  [{'ok' if passed else 'FAIL'}] {label}")

    print_scope(instance)


def print_scope(instance) -> None:
    """State plainly how much of the real network this run actually covers."""
    if not instance.is_subset:
        return
    print(f"\n  Scope: this run optimizes {instance.size} of the "
          f"{instance.total_stations} stations in the dataset.")
    print(f"  It does not solve the full {instance.total_stations}-station "
          f"network - the standard TSP QUBO needs O(n^2) variables, so that")
    print(f"  would take ({instance.total_stations}-1)^2 = "
          f"{instance.full_network_qubits} qubits. The full network is solved "
          f"classically by Phase 1")
    print(f"  (run_phase1.py); the stations above were selected from that same "
          f"unmodified dataset.")


def print_comparison(result, references) -> None:
    """QAOA next to the classical baseline and the true optimum."""
    optimum = next(
        (r for r in references if r.label.startswith("Exact optimum")), None
    )
    rows = [(r.label, r.total_distance_km) for r in references
            if not r.label.startswith("Exact optimum")]
    rows.append(("QAOA (approximate)", result.total_distance_km))
    if optimum:
        rows.append((optimum.label, optimum.total_distance_km))

    print("\n  Same instance, same Distance_km cost:")
    width = max(len(label) for label, _ in rows)
    for label, km in rows:
        print(f"    {label:<{width}} : {km:>12,.3f} km")

    if optimum and optimum.total_distance_km > 0 and result.route:
        gap = (result.total_distance_km / optimum.total_distance_km - 1.0) * 100
        verdict = ("matched the optimum on this instance" if gap < 1e-9
                   else f"came out {gap:.3f}% longer than the optimum")
        print(f"\n    QAOA {verdict}. QAOA is a heuristic, so this is an")
        print("    observation about this run, not a guarantee.")


def print_pipeline(instance, result) -> None:
    """Diagnostics: how the problem was transformed and how the search went."""
    print(RULE)
    print("PIPELINE (diagnostics)")
    print(RULE)
    print("  TSP  -> QUBO  -> Ising  -> QAOA")
    print(f"    TSP     : {instance.size} stations, "
          f"{instance.size * (instance.size - 1) // 2} pairwise costs, "
          f"start pinned to position 0")
    print(f"              (subset of the full {instance.total_stations}-station "
          f"/ {instance.total_lines}-line network)")
    print(f"    QUBO    : {result.num_qubits} binary variables, "
          f"{result.qubo_terms} terms, penalty weight {result.penalty:,.3f}")
    print(f"    Ising   : {result.hamiltonian_terms} Pauli-Z terms on "
          f"{result.num_qubits} qubits")
    print(f"    QAOA    : depth p={result.reps}, {2 * result.reps} angles, "
          f"COBYLA")
    print()
    print("  Why a subset - the QUBO needs (n-1)^2 qubits, i.e. O(n^2):")
    for n in (4, 5, 6, instance.total_stations):
        if n < 3:
            continue
        tag = "  <- full network" if n == instance.total_stations else ""
        mark = "  <- this run" if n == instance.size else ""
        print(f"    n = {n:>2} stations -> {(n - 1) ** 2:>4} qubits{tag}{mark}")
    print()
    print(f"  Objective evaluations : {result.evaluations}")
    print(f"  Circuit runs          : {result.circuit_runs}")
    print(f"  Shots drawn           : {result.total_samples:,}")
    print(f"  Feasible samples      : {result.feasible_samples:,} "
          f"({result.feasible_fraction * 100:.2f}% decoded to a valid tour)")
    print(f"  Distinct valid tours  : {result.distinct_feasible_tours} "
          f"of {_factorial(instance.size - 1)} possible")
    baseline = _factorial(instance.size - 1) / (2 ** result.num_qubits)
    if baseline:
        print(f"  vs blind guessing     : {baseline * 100:.4f}% of random "
              f"bitstrings are valid tours "
              f"({result.feasible_fraction / baseline:.0f}x concentration)")
    if result.best_qubo_energy is not None:
        print(f"  Best QUBO energy      : {result.best_qubo_energy:,.3f}")
    print()


def _factorial(n: int) -> int:
    total = 1
    for i in range(2, n + 1):
        total *= i
    return total


def _wrap_route(route: list) -> list:
    return [" -> ".join(route[i:i + 3]) for i in range(0, len(route), 3)]


def print_ibm_check() -> int:
    """Local-only report on the IBM credential configuration.

    Makes no network call, submits no job, and prints no secret value.
    """
    print(RULE)
    print("IBM QUANTUM CONFIGURATION CHECK (local only - nothing is contacted)")
    print(RULE)
    print()
    print(f"  .env file          : {ENV_FILE}")
    print(f"  .env present       : {'yes' if env_file_present() else 'no'}")
    covered = gitignore_covers_env()
    print(f"  .env git-ignored   : {'yes' if covered else 'NO - fix .gitignore'}")
    print()

    status = credential_status()
    width = max(len(name) for name, _, _, _, _ in status)
    missing_required = []
    for name, required, present, description, hint in status:
        tag = "required" if required else "optional"
        print(f"  {name:<{width}}  {tag:<8}  {description}")
        print(f"  {'':<{width}}            {hint}")
        if required and not present:
            missing_required.append(name)

    print()
    if missing_required:
        print("  Not ready: " + ", ".join(missing_required) + " is not set.")
        print(f"  Put it in {ENV_FILE} as:")
        print(f"      {TOKEN_VAR}=your-api-key")
        print("  or export it into the environment. Never commit the value.")
    else:
        print("  Ready. Run a hardware job with:")
        print('      python run_phase2.py --start "Mysuru Substation" --mode ibm')
    print(RULE)
    print()
    return 0 if not missing_required and covered else 7


def route_chain_lines(closed_route: list, width: int = 72) -> list:
    """The complete route as `A -> B -> ... -> A`, wrapped only where it must be.

    Every station is kept. The wrap falls on a ` -> ` boundary and a line that
    continues keeps its trailing arrow, so the chain reads unbroken down the
    page. Nothing is abbreviated, truncated or elided.
    """
    lines = []
    current = ""
    for name in closed_route:
        if not current:
            current = name
            continue
        if len(current) + len(f" -> {name}") > width:
            lines.append(f"{current} ->")
            current = name
        else:
            current += f" -> {name}"
    if current:
        lines.append(current)
    return lines


def print_routes(nn_result, hybrid_result) -> None:
    """The full tour each solver travelled, start station at both ends.

    This is a result, not diagnostics, so it prints on every run. Both routes
    come from the same network and the same starting station, and each lists
    all of its stations followed by the start again.
    """
    for heading, closed_route in (
        ("Classical NN route", nn_result.closed_route),
        ("Hybrid QAOA route", hybrid_result.tour.closed_route),
    ):
        print()
        print(f"  {heading}:")
        for line in route_chain_lines(closed_route):
            print(f"    {line}")


class SweepReporter:
    """`--verbose` progress for the hybrid loop.

    Prints one line per sweep and one line per accepted improvement. Purely an
    observer: `hybrid_solve` calls it after a window is decided, so whether it
    exists or the progress hook is `None` makes no difference to the tour.
    """

    def __init__(self, start_km: float):
        self.km = start_km
        self.sweep = 0

    def __call__(self, sweep: int, window_index: int, current_km: float) -> None:
        if sweep != self.sweep:
            if self.sweep:
                print(f"    sweep {self.sweep} done: {self.km:,.3f} km")
            self.sweep = sweep
        if current_km < self.km - 1e-9:
            print(f"    sweep {sweep}, window {window_index:>2}: "
                  f"{self.km:,.3f} -> {current_km:,.3f} km")
            self.km = current_km

    def done(self) -> None:
        """Close off the last sweep, which has no successor to trigger it."""
        if self.sweep:
            print(f"    sweep {self.sweep} done: {self.km:,.3f} km")


def solver_line(label: str, distance_km: float, elapsed: str, order: list,
                total_stations: int, checks: list) -> str:
    """One line per solver: distance, execution time, coverage, validity.

    The two solvers print through this same function, so their numbers line up
    column for column and can be read against each other at a glance.
    """
    visited = len(set(order))
    valid = all(passed for _, passed in checks)
    return (f"  {label:<18} : {distance_km:>10,.3f} km   {elapsed:>10}   "
            f"{visited}/{total_stations} stations   "
            f"{'route valid' if valid else 'ROUTE INVALID'}")


def print_short_comparison(comparison) -> None:
    """The closing verdict on a normal run. `--verbose` adds the full framing."""
    km = abs(comparison.improvement_km)
    percent = abs(comparison.improvement_percent)
    if comparison.winner == "hybrid":
        verdict = (f"hybrid QAOA is {km:,.3f} km ({percent:.2f}%) shorter "
                   f"than classical NN.")
    elif comparison.winner == "classical":
        verdict = (f"classical NN is {km:,.3f} km ({percent:.2f}%) shorter "
                   f"than hybrid QAOA.")
    else:
        verdict = "both solvers found tours of the same length."
    print(f"  Result             : {verdict}")
    print("                       QAOA is the engine inside a classical "
          "reoptimization")
    print("                       loop; no quantum advantage is claimed.")


def run_full_network(args) -> int:
    """Full 26-station workflow: classical NN vs hybrid QAOA, plus the maps."""
    import os

    from phase1.nn_tsp import solve as nn_solve

    from .comparison import (DISTANCE_DECIMALS, build_comparison,
                             same_problem_checks)
    from .hybrid import hybrid_solve, validate_full_tour
    from .visualize import (NN_LEGEND, NN_TITLE, QAOA_LEGEND, QAOA_TITLE,
                            render_comparison, render_route_map, same_layout)

    try:
        dataset = load_dataset(args.data)
    except DatasetError as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2

    network = Network(dataset)
    try:
        network.require_connected()
        start = args.start or choose_start(network)
        start = resolve_station(network, start)
    except NetworkError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 3
    except SolverError as exc:
        print(f"Invalid starting station: {exc}", file=sys.stderr)
        return 4

    summary = network.summary()
    total_stations = summary["stations"]
    print(RULE)
    print("GRIDOPT - PHASE 2 : FULL-NETWORK CLASSICAL vs HYBRID QUANTUM")
    print(RULE)
    print()
    print(f"  Network            : {total_stations} stations, "
          f"{summary['routable_lines']} transmission lines")
    print(f"  Starting station   : {start}")
    if args.verbose:
        print(f"  Dataset            : {dataset.path}")
        print(f"  Cost function      : Distance_km shortest path "
              f"(identical for both solvers)")
    print()

    # --- classical baseline: Phase 1, unmodified --------------------------
    nn_result = nn_solve(network, start)
    nn_checks = validate_full_tour(network, nn_result, start, network.names)
    print(solver_line(
        "Classical NN",
        round(nn_result.total_distance_km, DISTANCE_DECIMALS),
        f"{nn_result.execution_time_s * 1000:.3f} ms",
        nn_result.order, total_stations, nn_checks,
    ))

    # --- hybrid: QAOA as the engine inside the reoptimization loop --------
    try:
        runner = make_runner("simulator", seed=args.seed)
    except BackendError as exc:
        print(f"Backend error: {exc}", file=sys.stderr)
        return 6

    if args.verbose:
        print(f"  {'QAOA loop':<18} : window W={args.window} "
              f"({args.window ** 2} qubits per subproblem), "
              f"up to {args.sweeps} sweeps")
        if args.window >= 5:
            print(f"    (note: {args.window ** 2}-qubit subproblems take about "
                  f"a minute each to simulate; expect a long run)")

    # Sweep-by-sweep and window-by-window progress is pipeline diagnostics,
    # not a result: --verbose only. `progress=None` is a pure no-op inside
    # `hybrid_solve`, so the tour it returns is byte-for-byte the same either
    # way.
    reporter = (SweepReporter(nn_result.total_distance_km)
                if args.verbose else None)

    hybrid_result = hybrid_solve(
        network, nn_result.order, runner,
        window=args.window, sweeps=args.sweeps, prune=not args.no_prune,
        reps=args.reps, shots=args.hybrid_shots, maxiter=args.hybrid_maxiter,
        restarts=args.hybrid_restarts, seed=args.seed, cvar_alpha=args.cvar,
        progress=reporter,
    )
    if reporter is not None:
        reporter.done()
    runner.close()
    hybrid_checks = validate_full_tour(
        network, hybrid_result.tour, start, network.names
    )
    print(solver_line(
        "Hybrid QAOA",
        round(hybrid_result.total_distance_km, DISTANCE_DECIMALS),
        f"{hybrid_result.execution_time_s:.2f} s",
        hybrid_result.tour.order, total_stations, hybrid_checks,
    ))

    comparison = build_comparison(
        network, dataset, nn_result, nn_checks,
        hybrid_result, hybrid_checks, start,
    )

    # --- validation, before anything is drawn -----------------------------
    # Always computed. Only the pass-by-pass listing is verbose-only: a normal
    # run reports validity per solver on the two lines above, and a FAILING
    # check is always shown, whatever the verbosity.
    problem_checks = same_problem_checks(network, nn_result, hybrid_result, start)
    all_checks = nn_checks + hybrid_checks + problem_checks
    everything_valid = all(passed for _, passed in all_checks)

    if args.verbose:
        print()
        print("  Validation - classical Nearest Neighbour:")
        for label, passed in nn_checks:
            print(f"    [{'ok' if passed else 'FAIL'}] {label}")
        print("\n  Validation - hybrid QAOA:")
        for label, passed in hybrid_checks:
            print(f"    [{'ok' if passed else 'FAIL'}] {label}")
        print("\n  Validation - same problem for both solvers:")
        for label, passed in problem_checks:
            print(f"    [{'ok' if passed else 'FAIL'}] {label}")

    # --- comparison -------------------------------------------------------
    print()
    print(f"  Difference         : {comparison.improvement_km:+,.3f} km "
          f"absolute, {comparison.improvement_percent:+.2f}% vs classical NN")
    print()
    print_short_comparison(comparison)

    # --- the complete route each solver travelled -------------------------
    print_routes(nn_result, hybrid_result)

    if args.verbose:
        print()
        print(RULE)
        print("COMPARISON - full network, both solvers, same cost function")
        print(RULE)
        width = max(len(label) for label, _, _ in comparison.table_rows())
        print(f"  {'':<{width}}   {'Classical NN':<22} {'Hybrid QAOA':<22}")
        for label, classical, quantum in comparison.table_rows():
            print(f"  {label:<{width}} : {classical:<22} {quantum:<22}")
        print()
        print(f"  Hybrid detail      : {comparison.hybrid_subproblems} QAOA "
              f"subproblems over {comparison.hybrid_sweeps} sweep(s), "
              f"{comparison.hybrid_accepted} improvements accepted"
              + (f", {comparison.hybrid_skipped} windows skipped unchanged"
                 if comparison.hybrid_skipped else ""))
        print(f"  QAOA configuration : window W={args.window} -> "
              f"{args.window ** 2} qubits per subproblem, depth p={args.reps}, "
              f"{args.hybrid_shots} shots,")
        print(f"                       COBYLA maxiter {args.hybrid_maxiter} x "
              f"{args.hybrid_restarts} restart(s), CVaR alpha={args.cvar}, "
              f"pruning {'on' if not args.no_prune else 'off'}")
        print(f"  Quantum backend    : {comparison.hybrid_backend}")
        print()
        print_full_framing(comparison)

    if not everything_valid:
        print("\n  Failed validation checks:", file=sys.stderr)
        for label, passed in all_checks:
            if not passed:
                print(f"    [FAIL] {label}", file=sys.stderr)
        print("\nValidation failed - refusing to write the maps.", file=sys.stderr)
        return 5

    # --- maps -------------------------------------------------------------
    os.makedirs(args.outputs, exist_ok=True)
    nn_png = os.path.join(args.outputs, "nn_full_route.png")
    qaoa_png = os.path.join(args.outputs, "qaoa_full_route.png")
    comparison_png = os.path.join(args.outputs, "nn_vs_qaoa_comparison.png")

    aligned = same_layout(network, mode=args.layout)
    try:
        # Map titles read the same displayed distances the comparison panel
        # and the terminal use, so no figure can disagree with the numbers.
        render_route_map(network, nn_result, nn_png,
                         f"{NN_TITLE} - {comparison.nn_distance_display:,.1f} km",
                         show_labels=not args.no_labels, layout_mode=args.layout,
                         route_label=NN_LEGEND)
        render_route_map(network, hybrid_result.tour, qaoa_png,
                         f"{QAOA_TITLE} - "
                         f"{comparison.hybrid_distance_display:,.1f} km",
                         show_labels=not args.no_labels, layout_mode=args.layout,
                         route_label=QAOA_LEGEND)
        render_comparison(nn_png, qaoa_png, comparison, comparison_png)
    except Exception as exc:
        print(f"\nVisualization failed ({exc}); the results above are still "
              f"valid.", file=sys.stderr)
        return 0

    # The same routes printed above, drawn leg by leg and numbered.
    print()
    print("  Generated graphs:")
    for path in (nn_png, qaoa_png, comparison_png):
        print(f"    {path}")
    if args.verbose:
        print(f"\n  Both route maps use the same station coordinates "
              f"(layout reproducible: {'yes' if aligned else 'NO'}), so the "
              f"routes can be compared directly.")
    print()
    print(RULE)
    print()
    return 0


def print_full_framing(comparison) -> None:
    """The scientific framing. Printed on every full-network run."""
    print("  How to read this:")
    print("    - QAOA is the optimization ENGINE INSIDE a classical "
          "full-network reoptimization")
    print(f"      loop. Each subproblem reorders {comparison.hybrid_window} "
          f"stations of the tour on "
          f"{comparison.hybrid_qubits} qubits;")
    print("      choosing the windows and accepting improvements is classical.")
    print("    - The QAOA subproblems do NOT independently solve the "
          f"{comparison.stations}-station TSP.")
    print("      The full network cannot be encoded directly: it would need "
          f"({comparison.stations}-1)^2 = "
          f"{(comparison.stations - 1) ** 2} qubits.")
    print("    - NO quantum advantage is claimed. This is a like-for-like "
          "comparison on one")
    print("      dataset, not evidence that quantum optimization is faster or "
          "better in general.")
    if comparison.winner == "classical":
        print("    - On this run the classical baseline was not beaten by the "
              "hybrid.")
    elif comparison.winner == "hybrid":
        print(f"    - On this run the hybrid shortened the classical tour by "
              f"{comparison.improvement_percent:.2f}%.")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.check_ibm:
        return print_ibm_check()

    if not args.subset:
        return run_full_network(args)

    try:
        dataset = load_dataset(args.data)
    except DatasetError as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2

    network = Network(dataset)

    try:
        start = args.start or choose_start(network)
        stations = (
            [s.strip() for s in args.stations.split(",") if s.strip()]
            if args.stations else None
        )
        instance = build_instance(
            network, start, size=args.size, stations=stations
        )
    except SolverError as exc:
        print(f"Instance error: {exc}", file=sys.stderr)
        return 4
    except NetworkError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 3

    if instance.num_qubits > args.max_qubits:
        print(
            f"Instance error: {instance.size} stations need "
            f"{instance.num_qubits} qubits, over the --max-qubits limit of "
            f"{args.max_qubits}. Simulating that many qubits is slow; use a "
            f"smaller --size, or raise --max-qubits deliberately.",
            file=sys.stderr,
        )
        return 4

    # --- pick the runners -------------------------------------------------
    loop_runner = None
    final_runner = None
    try:
        if args.mode == "simulator":
            loop_runner = make_runner("simulator", seed=args.seed)
            final_runner = loop_runner
        else:
            if args.ibm_strategy == "full":
                loop_runner = make_runner(
                    "ibm", backend_name=args.ibm_backend, use_session=True
                )
                final_runner = loop_runner
            else:
                # Train the angles locally, spend one hardware job on the answer.
                loop_runner = make_runner("simulator", seed=args.seed)
                final_runner = make_runner(
                    "ibm", backend_name=args.ibm_backend, use_session=False
                )
    except BackendError as exc:
        print(f"Backend error: {exc}", file=sys.stderr)
        return 6

    try:
        result = run_qaoa(
            instance,
            reps=args.reps,
            shots=args.shots,
            maxiter=args.maxiter,
            restarts=args.restarts,
            seed=args.seed,
            penalty=args.penalty,
            cvar_alpha=args.cvar,
            runner=loop_runner,
            final_runner=final_runner,
            final_shots=args.ibm_shots if args.mode == "ibm" else None,
        )
    except BackendError as exc:
        print(f"Backend error: {exc}", file=sys.stderr)
        return 6
    finally:
        for runner in {id(loop_runner): loop_runner,
                       id(final_runner): final_runner}.values():
            if runner is not None:
                runner.close()

    print_summary(dataset, instance, result)

    if not args.no_compare:
        references = [nearest_neighbour(network, instance),
                      brute_force_optimum(instance)]
        print_comparison(result, references)

    print(RULE)
    print()

    if args.verbose:
        print_pipeline(instance, result)

    if not result.valid:
        print("QAOA did not return a valid tour on this run. Try more --shots, "
              "a deeper --reps, more --restarts, or a different --seed.",
              file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
