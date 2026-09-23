"""Side-by-side comparison of the two FULL-network solvers.

Both sides solve the identical problem: the same 26 stations, the same 38
transmission lines, the same starting station, and the same `Distance_km`
shortest-path cost function from `phase1.network.Network.travel_cost`. That is
what makes the numbers comparable; `same_problem_checks` asserts it rather than
assuming it.

Scientific framing, applied throughout the output:

  * QAOA is the optimization engine *inside* a classical full-network
    reoptimization loop. The QAOA subproblems do not independently solve the
    26-station TSP.
  * No quantum advantage is claimed. Where the classical baseline wins, the
    output says so plainly.
"""

from __future__ import annotations

from dataclasses import dataclass

# Every distance Phase 2 reports is shown to this many decimals, and every
# percentage to this many. The comparison numbers are derived from the ROUNDED
# distances so the printed difference and the printed percentage can be
# recomputed from the printed distances - terminal, figure and report agree.
DISTANCE_DECIMALS = 3
PERCENT_DECIMALS = 2


@dataclass
class Comparison:
    """Everything needed to report the classical / hybrid comparison."""

    start: str
    stations: int
    lines: int
    dataset_path: str

    nn_distance_km: float
    nn_time_s: float
    nn_valid: bool
    nn_checks: list

    hybrid_distance_km: float
    hybrid_time_s: float
    hybrid_valid: bool
    hybrid_checks: list

    hybrid_window: int
    hybrid_qubits: int
    hybrid_subproblems: int
    hybrid_skipped: int
    hybrid_accepted: int
    hybrid_sweeps: int
    hybrid_mode: str
    hybrid_backend: str

    same_cost_function: bool = True

    @property
    def nn_distance_display(self) -> float:
        """The classical distance exactly as it is displayed, rounded once."""
        return round(self.nn_distance_km, DISTANCE_DECIMALS)

    @property
    def hybrid_distance_display(self) -> float:
        """The hybrid distance exactly as it is displayed, rounded once."""
        return round(self.hybrid_distance_km, DISTANCE_DECIMALS)

    @property
    def improvement_km(self) -> float:
        """Displayed NN distance minus displayed hybrid distance.

        Derived from the displayed values, not the raw floats, so subtracting
        the two printed distances by hand reproduces this number exactly.
        """
        return round(self.nn_distance_display - self.hybrid_distance_display,
                     DISTANCE_DECIMALS)

    @property
    def improvement_percent(self) -> float:
        """`improvement_km` as a percentage of the displayed NN distance."""
        if not self.nn_distance_display:
            return 0.0
        return round(
            self.improvement_km / self.nn_distance_display * 100.0,
            PERCENT_DECIMALS,
        )

    @property
    def winner(self) -> str:
        if abs(self.improvement_km) < 1e-9:
            return "tie"
        return "hybrid" if self.improvement_km > 0 else "classical"

    def table_rows(self) -> list:
        """(label, classical, hybrid) triples for the report and the figure."""
        return [
            ("Total distance",
             f"{self.nn_distance_display:,.{DISTANCE_DECIMALS}f} km",
             f"{self.hybrid_distance_display:,.{DISTANCE_DECIMALS}f} km"),
            ("Execution time",
             f"{self.nn_time_s * 1000:.3f} ms",
             f"{self.hybrid_time_s:.2f} s"),
            ("Stations visited",
             f"{self.stations} (each once)",
             f"{self.stations} (each once)"),
            ("Route valid",
             "yes" if self.nn_valid else "NO",
             "yes" if self.hybrid_valid else "NO"),
            ("Improvement vs NN",
             "baseline",
             f"{self.improvement_km:+,.{DISTANCE_DECIMALS}f} km "
             f"({self.improvement_percent:+.{PERCENT_DECIMALS}f}%)"),
        ]

    def framing_note(self) -> str:
        return (
            "Same dataset, same 26 stations / 38 lines, same Distance_km cost. "
            "QAOA is the optimization engine inside a classical full-network "
            "reoptimization loop - the subproblems do not solve the whole TSP "
            "on their own. No quantum advantage is claimed."
        )


def same_problem_checks(network, nn_result, hybrid_result, start: str) -> list:
    """Assert both solvers really were given the identical problem."""
    nn_stations = sorted(nn_result.order)
    hybrid_stations = sorted(hybrid_result.tour.order)
    return [
        ("both solve the same station set",
         nn_stations == hybrid_stations == sorted(network.names)),
        ("both start from the same station",
         nn_result.start == hybrid_result.tour.start == start),
        ("both use the same Distance_km travel costs",
         _costs_agree(network, nn_result) and
         _costs_agree(network, hybrid_result.tour)),
        ("both close the tour",
         nn_result.closed_route[-1] == start and
         hybrid_result.tour.closed_route[-1] == start),
    ]


def _costs_agree(network, result) -> bool:
    """Every reported leg cost is the network's own travel cost."""
    return all(
        abs(leg.distance_km - network.travel_cost(leg.origin, leg.destination))
        < 1e-9
        for leg in result.legs
    )


def build_comparison(network, dataset, nn_result, nn_checks,
                     hybrid_result, hybrid_checks, start: str) -> Comparison:
    summary = network.summary()
    return Comparison(
        start=start,
        stations=summary["stations"],
        lines=summary["routable_lines"],
        dataset_path=str(dataset.path),
        nn_distance_km=nn_result.total_distance_km,
        nn_time_s=nn_result.execution_time_s,
        nn_valid=all(passed for _, passed in nn_checks),
        nn_checks=nn_checks,
        hybrid_distance_km=hybrid_result.total_distance_km,
        hybrid_time_s=hybrid_result.execution_time_s,
        hybrid_valid=all(passed for _, passed in hybrid_checks),
        hybrid_checks=hybrid_checks,
        hybrid_window=hybrid_result.window,
        hybrid_qubits=hybrid_result.qubits_per_subproblem,
        hybrid_subproblems=hybrid_result.subproblems_solved,
        hybrid_skipped=hybrid_result.subproblems_skipped,
        hybrid_accepted=hybrid_result.improvements_accepted,
        hybrid_sweeps=hybrid_result.sweeps_run,
        hybrid_mode=hybrid_result.mode,
        hybrid_backend=hybrid_result.backend_description,
    )
