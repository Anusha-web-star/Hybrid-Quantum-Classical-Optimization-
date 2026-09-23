"""An actual solver run, turned into retrievable context.

The caller may attach the run it is looking at - the exact object
`POST /solve/compare` returned, which the dashboard already holds - and the
assistant then answers questions about that run.

The whole point of this module is what it refuses to do. It never invents a
route, a distance, a runtime, a window size or a qubit count, and it never fills
a missing field with a plausible one. If a field is absent from the payload, the
chunk says it is absent. If no run is attached at all, no solver chunk exists,
retrieval finds nothing about routes, and the assistant says the information is
unavailable - which is the correct answer, because it is.
"""

from __future__ import annotations

from typing import Any, Optional

from app.assistant.documents import Chunk, number

MISSING = "not present in the supplied run output"


def _get(payload: Any, *path: str, default: Any = None) -> Any:
    """Walk a nested dict path, returning `default` at the first gap."""
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current if current is not None else default


def _route_line(closed_route: Optional[list]) -> str:
    if not closed_route:
        return MISSING
    return " -> ".join(str(stop) for stop in closed_route)


def _legs_block(legs: Optional[list], limit: int = 30) -> list:
    if not legs:
        return [f"Route legs: {MISSING}"]

    lines = ["Route legs (step: origin -> destination, distance, direct line?):"]
    for leg in legs[:limit]:
        direct = leg.get("is_direct")
        via = leg.get("via") or []
        marker = "direct line" if direct else (
            "no direct line; shortest path via " + ", ".join(via)
            if via else "no direct line"
        )
        lines.append(
            f"  {leg.get('step', '?')}: {leg.get('origin', '?')} -> "
            f"{leg.get('destination', '?')}, "
            f"{number(leg.get('distance_km'), 'km')} ({marker})"
        )
    if len(legs) > limit:
        lines.append(f"  ... {len(legs) - limit} further legs not listed here.")
    return lines


def _tour_block(label: str, tour: Optional[dict],
                with_route: bool = True, with_checks: bool = True) -> list:
    if not isinstance(tour, dict):
        return [f"{label}: {MISSING}"]

    checks = (tour.get("checks") or []) if with_checks else []
    check_lines = [
        f"  - {check.get('label', '?')}: "
        f"{'passed' if check.get('passed') else 'FAILED'}"
        for check in checks
    ]

    return [
        f"{label}:",
        f"  Starting station: {tour.get('start', MISSING)}",
        f"  Total route distance: {number(tour.get('total_distance_km'), 'km')}",
        f"  Runtime (execution time measured for this run): "
        f"{number(tour.get('execution_time_s'), 'seconds')}",
        f"  Stations visited: {tour.get('stations_visited', MISSING)}",
        f"  Legs with a direct transmission line: "
        f"{tour.get('direct_legs', MISSING)} of {len(tour.get('legs') or []) or MISSING}",
        f"  Route validity: {'valid' if tour.get('valid') else 'NOT valid'}",
        *(["  Validation checks:"] + check_lines if check_lines else []),
        *([f"  Full closed route: {_route_line(tour.get('closed_route'))}"]
          if with_route else []),
    ]


#: Rupee figures restated at the scale people actually speak them in.
#:
#: Computed here, in Python, from the run's own value - never by the model. The
#: assistant is forbidden to calculate, and a lakh/crore conversion is a
#: calculation; carrying the converted form in the context is what lets it
#: answer "about how many crore a year?" without doing arithmetic. Derived from
#: the figure the API returned for THIS run, so it moves when the run moves.
LAKH = 100_000
CRORE = 10_000_000


def _indian_scale(value) -> str:
    """'(about Rs. 32.33 lakh)' for a rupee figure, or '' when there is none."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    if value != value:  # NaN
        return ""
    magnitude = abs(value)
    if magnitude >= CRORE:
        return f" (about Rs. {value / CRORE:,.2f} crore)"
    if magnitude >= LAKH:
        return f" (about Rs. {value / LAKH:,.2f} lakh)"
    return ""


def _money_line(label: str, value, unit: str) -> str:
    return f"  {label}: {number(value, unit, 2)}{_indian_scale(value)}"


def _tariff_line(tariff: dict) -> str:
    return (f"Tariff applied to this run: Rs. {tariff.get('inr_per_kwh', MISSING)} "
            f"per kWh ({tariff.get('component', MISSING)}, "
            f"{tariff.get('category', MISSING)}).")


#: Attached to every money-bearing run chunk.
#:
#: The same rule as the project's other standing caveats, at run scope: a rupee
#: figure from this project may never be read as a bill. It is repeated per
#: chunk rather than stated once for the run, because retrieval hands over
#: whichever chunk matches - previously the caveats lived at the END of one long
#: energy chunk and were the first thing the per-chunk cap cut off.
MONEY_CAVEAT = (
    "HOW TO READ THESE RUPEE FIGURES: an ENERGY CHARGE ONLY - the value of the "
    "lost energy, and not an electricity bill. The annualised figure is an "
    "ESTIMATE assuming this modeled loss holds continuously for all 8,760 "
    "hours of a year; never give it as an actual annual loss."
)


def solver_run_chunks(run: dict) -> list:
    """Chunks describing one actual optimization run.

    `run` is the `/solve/compare` response body (or the subset of it the client
    holds). Missing sections are reported as missing.
    """
    if not isinstance(run, dict) or not run:
        return []

    chunks: list = []
    start = run.get("start") or _get(run, "classical", "start") or MISSING
    classical_tour = _get(run, "classical", "tour")
    hybrid_tour = _get(run, "hybrid", "tour")
    detail = _get(run, "hybrid", "detail")
    comparison = run.get("comparison")
    energy = run.get("energy")

    # --- the two routes, headline figures ----------------------------------
    #
    # The full station-by-station route used to live here too, which made this
    # chunk two and a half times the per-chunk cap: everything after the NN
    # tour was cut off before the model saw it. The orderings now have their own
    # chunk each, below, and this one answers "what distance did this run
    # produce?" whole.
    routes_text = "\n".join([
        "SOLVER RUN - the optimization run currently open in the dashboard.",
        "These are actual outputs returned by this project's API for this run. "
        "Nothing here is illustrative.",
        "Answers questions such as: what was the hybrid distance in this run? "
        "what did NN produce? how long did this run take? is the route valid?",
        f"Starting station for the run: {start}",
        "",
        *_tour_block(
            "CLASSICAL NEAREST NEIGHBOUR (NN) route - algorithm "
            f"{_get(run, 'classical', 'algorithm', default='classical-nearest-neighbour')}",
            classical_tour, with_route=False, with_checks=False,
        ),
        "",
        *_tour_block(
            "HYBRID QAOA route - algorithm "
            f"{_get(run, 'hybrid', 'algorithm', default='hybrid-qaoa-reoptimization')}",
            hybrid_tour, with_route=False, with_checks=False,
        ),
    ])
    chunks.append(Chunk(
        id="run:routes",
        kind="solver",
        title=f"Solver run: NN and Hybrid QAOA routes from {start}",
        locator="POST /solve/compare - current run",
        text=routes_text,
        metadata={"start": start},
    ))

    # --- the visiting order of each route ----------------------------------
    for label, tour, chunk_id in (
        ("CLASSICAL NEAREST NEIGHBOUR (NN)", classical_tour, "run:route:classical"),
        ("HYBRID QAOA", hybrid_tour, "run:route:hybrid"),
    ):
        if not isinstance(tour, dict) or not tour.get("closed_route"):
            continue
        chunks.append(Chunk(
            id=chunk_id,
            kind="solver",
            title=f"Solver run: {label} visiting order",
            locator="POST /solve/compare - current run",
            text="\n".join([
                f"SOLVER RUN - the {label} route this run produced, station by "
                "station. Actual output of this run.",
                f"Total route distance: {number(tour.get('total_distance_km'), 'km')}",
                f"Stations visited: {tour.get('stations_visited', MISSING)}",
                f"Route validity: {'valid' if tour.get('valid') else 'NOT valid'}",
                *([" Validation checks:"] + [
                    f"  - {check.get('label', '?')}: "
                    f"{'passed' if check.get('passed') else 'FAILED'}"
                    for check in (tour.get("checks") or [])
                ] if tour.get("checks") else []),
                "",
                f"Full closed route: {_route_line(tour.get('closed_route'))}",
            ]),
            metadata={"route": label},
        ))

    # --- the legs, indexed separately so a per-leg question can find them ---
    for label, tour, chunk_id in (
        ("Classical Nearest Neighbour", classical_tour, "run:legs:classical"),
        ("Hybrid QAOA", hybrid_tour, "run:legs:hybrid"),
    ):
        if not isinstance(tour, dict) or not tour.get("legs"):
            continue
        chunks.append(Chunk(
            id=chunk_id,
            kind="solver",
            title=f"Solver run: {label} route legs",
            locator="POST /solve/compare - current run",
            text="\n".join([
                f"SOLVER RUN - {label} route, leg by leg. Actual output of this run.",
                f"Starting station: {tour.get('start', start)}",
                f"Total route distance: {number(tour.get('total_distance_km'), 'km')}",
                "",
                *_legs_block(tour.get("legs")),
                "",
                "A leg marked 'no direct line' means the two stations are not "
                "joined by a single transmission line; the distance is the "
                "shortest path through the stations listed, which are passed "
                "through without being counted as visited at that point.",
            ]),
            metadata={"route": label},
        ))

    # --- how the hybrid search ran ----------------------------------------
    if isinstance(detail, dict):
        detail_text = "\n".join([
            "SOLVER RUN - hybrid QAOA execution detail. Actual configuration "
            "and counters for this run.",
            "Answers: how many qubits were used in this run, what window and "
            "how many sweeps, which backend, and how many improvements were "
            "accepted.",
            f"Execution mode: {detail.get('mode', MISSING)}",
            f"Backend / simulator used: {detail.get('backend', MISSING)}",
            f"QAOA window size W: {detail.get('window', MISSING)}",
            "QUBITS USED IN THIS RUN: "
            f"{detail.get('qubits_per_subproblem', MISSING)} qubits. That is "
            "the width of every QAOA circuit this run executed, and it is the "
            "whole answer to 'how many qubits were used'. The subproblems run "
            "one after another on the same circuit width, so qubits are NOT "
            "added up across subproblems or sweeps: do not multiply this "
            "number by anything.",
            f"Sweeps run: {detail.get('sweeps_run', MISSING)}",
            f"Subproblems solved: {detail.get('subproblems_solved', MISSING)}",
            f"Subproblems skipped (pruned as unable to improve): "
            f"{detail.get('subproblems_skipped', MISSING)}",
            f"Improvements accepted: {detail.get('improvements_accepted', MISSING)}",
            f"QAOA evaluations: {detail.get('qaoa_evaluations', MISSING)}",
            "Distance of the classical tour the reoptimization started from: "
            f"{number(detail.get('start_distance_km'), 'km')}",
            "",
            "Read this together with the objective: the hybrid loop accepts a "
            "window reordering only when it shortens the total route distance. "
            "The number of accepted improvements is therefore the number of "
            "times QAOA found a shorter ordering, not a measure of any energy "
            "saving and not evidence of quantum advantage.",
        ])
        chunks.append(Chunk(
            id="run:hybrid-detail",
            kind="solver",
            title="Solver run: hybrid QAOA execution detail",
            locator="POST /solve/compare - current run, hybrid.detail",
            text=detail_text,
            metadata={"mode": detail.get("mode"), "window": detail.get("window")},
        ))

    # --- the comparison ----------------------------------------------------
    if isinstance(comparison, dict):
        checks = comparison.get("same_problem_checks") or []
        comparison_text = "\n".join([
            "SOLVER RUN - comparison of the two routes. Actual output of this run.",
            f"Starting station: {comparison.get('start', start)}",
            f"Stations in the problem: {comparison.get('stations', MISSING)}",
            f"Transmission lines in the problem: {comparison.get('lines', MISSING)}",
            f"Dataset used: {comparison.get('dataset_path', MISSING)}",
            f"NN route distance: {number(comparison.get('nn_distance_km'), 'km')}",
            f"NN runtime: {number(comparison.get('nn_time_s'), 'seconds')}",
            f"NN route valid: {comparison.get('nn_valid', MISSING)}",
            f"Hybrid QAOA route distance: "
            f"{number(comparison.get('hybrid_distance_km'), 'km')}",
            f"Hybrid QAOA runtime: {number(comparison.get('hybrid_time_s'), 'seconds')}",
            f"Hybrid route valid: {comparison.get('hybrid_valid', MISSING)}",
            f"Improvement (NN distance minus hybrid distance): "
            f"{number(comparison.get('improvement_km'), 'km')}",
            f"Improvement as a percentage of the NN distance: "
            f"{number(comparison.get('improvement_percent'), '%')}",
            f"Shorter route: {comparison.get('winner', MISSING)}",
            *([f"Same-problem checks:"] + [
                f"  - {check.get('label', '?')}: "
                f"{'passed' if check.get('passed') else 'FAILED'}"
                for check in checks
            ] if checks else []),
            "",
            f"Framing recorded with this comparison: "
            f"{comparison.get('framing_note', MISSING)}",
            "",
            "The improvement is a ROUTE DISTANCE difference only. It is not an "
            "energy saving and not a monetary saving, and it does not on its "
            "own establish quantum advantage.",
        ])
        chunks.append(Chunk(
            id="run:comparison",
            kind="solver",
            title="Solver run: NN vs Hybrid QAOA comparison",
            locator="POST /solve/compare - current run, comparison",
            text=comparison_text,
            metadata={"winner": comparison.get("winner"),
                      "improvement_km": comparison.get("improvement_km")},
        ))

    # --- the energy / money analysis of the two routes ---------------------
    if isinstance(energy, dict):
        chunks.extend(_energy_chunks(energy))

    return chunks


def _route_energy_block(label: str, route: Optional[dict]) -> list:
    if not isinstance(route, dict):
        return [f"{label}: {MISSING}"]

    missing_loss = route.get("lines_missing_loss") or []
    unmatched = route.get("unmatched_steps") or []

    return [
        f"{label}:",
        f"  Total route distance: {number(route.get('total_distance_km'), 'km')}",
        f"  Distinct transmission lines used: {route.get('line_count', MISSING)}",
        f"  Line traversals: {route.get('traversal_count', MISSING)}",
        f"  Lines crossed more than once: {route.get('revisited_lines', MISSING)}",
        "  Total modeled energy loss (sum of Energy_Loss_MW over the DISTINCT "
        f"lines used): {number(route.get('total_energy_loss_mw'), 'MW')}",
        "  Same figure as energy per hour: "
        f"{number(route.get('total_energy_loss_kwh_per_hour'), 'kWh per hour')}",
        _money_line("Loss cost per hour (hourly loss cost)",
                    route.get("loss_cost_per_hour_inr"), "INR per hour"),
        _money_line("Annualised loss cost = the estimated annual "
                    "(annualized) loss cost, hourly x 8760",
                    route.get("loss_cost_per_year_inr"), "INR per year"),
        f"  Costing complete for every line used: {route.get('complete', MISSING)}",
        *([f"  Lines used that carry no Energy_Loss_MW value: {len(missing_loss)} "
           "- the total is therefore a lower bound and nothing was estimated "
           "in their place."] if missing_loss else []),
        *([f"  Route steps that matched no transmission line: {len(unmatched)}"]
          if unmatched else []),
    ]


def _route_energy_headline(label: str, route: Optional[dict]) -> list:
    """The three figures a comparison needs, without the full breakdown."""
    if not isinstance(route, dict):
        return [f"{label}: {MISSING}"]
    return [
        f"{label}:",
        "  Total modeled energy loss: "
        f"{number(route.get('total_energy_loss_mw'), 'MW')}",
        _money_line("Loss cost per hour",
                    route.get("loss_cost_per_hour_inr"), "INR per hour"),
        _money_line("Annualised (estimated annual) loss cost",
                    route.get("loss_cost_per_year_inr"), "INR per year"),
    ]


def _energy_chunks(energy: dict) -> list:
    """The energy-loss and monetary analysis attached to this run.

    THREE chunks, not one, and the reason is the bug this split fixed.

    All of it used to be a single 3,400-character chunk. Two things went wrong
    with that. It was longer than `context.MAX_CHUNK_CHARS`, so the tariff rate,
    the annualisation note and the caveats - everything after the two routes -
    were cut off before the model saw them. And BM25 normalises by length, so
    one long chunk scored below short documentation chunks on the very question
    it alone could answer ("what's the estimated annual loss cost for this
    run?"), and lost its place in the prompt budget to them.

    Split per route, each piece fits whole, carries its own rupee figures, its
    own tariff line and its own caveat, and competes on the terms of the
    question actually asked - "the hybrid modeled loss" or "the NN modeled
    loss", not "energy".
    """
    tariff = energy.get("tariff") or {}
    caveats = []
    for route in ("classical", "hybrid"):
        for caveat in (energy.get(route) or {}).get("caveats", []) or []:
            if caveat not in caveats:
                caveats.append(caveat)

    chunks: list = []

    for key, label, short in (
        ("classical", "CLASSICAL NEAREST NEIGHBOUR (NN)", "NN"),
        ("hybrid", "HYBRID QAOA", "hybrid"),
    ):
        route = energy.get(key)
        if not isinstance(route, dict):
            continue
        chunks.append(Chunk(
            id=f"run:energy:{key}",
            kind="solver",
            title=f"Solver run: {label} route energy loss and loss cost",
            locator="POST /solve/compare - current run, energy."
                    f"{key}",
            text="\n".join([
                f"SOLVER RUN - modeled energy loss and estimated loss cost for "
                f"the {label} route of the run currently open in the dashboard. "
                "Actual output of this run; nothing here is illustrative.",
                f"Answers: the {short} modeled loss for this run, its loss "
                f"cost per hour, and its estimated annual (annualised, "
                f"annualized, per year, crore) loss cost.",
                "",
                *_route_energy_block(f"{label} route", route),
                "",
                _tariff_line(tariff),
                f"Hours assumed per year: {energy.get('hours_per_year', MISSING)}",
                "",
                MONEY_CAVEAT,
            ]),
            metadata={"route": key,
                      "total_energy_loss_mw": route.get("total_energy_loss_mw"),
                      "loss_cost_per_year_inr": route.get("loss_cost_per_year_inr")},
        ))

    text = "\n".join([
        "SOLVER RUN - the two routes' energy loss and loss cost compared, and "
        "the tariff basis. Actual output of this run.",
        "Answers: which route loses less, what separates them, and what tariff "
        "this run was costed at.",
        "",
        # Headline figures only: each route's full breakdown is its own chunk
        # above, and repeating it here would put this one back over the cap.
        *_route_energy_headline("CLASSICAL NEAREST NEIGHBOUR (NN) route",
                                energy.get("classical")),
        "",
        *_route_energy_headline("HYBRID QAOA route", energy.get("hybrid")),
        "",
        # Obligations before detail. This chunk can still exceed the per-chunk
        # cap on a run with long station names, and a cap cuts the END - so the
        # caveat and the tariff sit above the differences, not below them.
        _tariff_line(tariff),
        MONEY_CAVEAT,
        "",
        "DIFFERENCES (classical minus hybrid; positive means hybrid is lower):",
        f"  Route distance difference: "
        f"{number(energy.get('distance_difference_km'), 'km')}",
        f"  Modeled energy loss difference: "
        f"{number(energy.get('energy_loss_difference_mw'), 'MW')}",
        f"  Hourly cost difference: "
        f"{number(energy.get('hourly_cost_difference_inr'), 'INR per hour', 2)}",
        f"  Annualised cost difference: "
        f"{number(energy.get('annual_cost_difference_inr'), 'INR per year', 2)}",
        f"  Route with the lower modeled loss: "
        f"{energy.get('lower_loss_route', MISSING)}",
        "",
        "",
        f"Tariff authority: {tariff.get('authority', MISSING)}. "
        f"Hours assumed per year: {energy.get('hours_per_year', MISSING)}.",
        "Neither solver optimized for energy loss or for cost: this is an "
        "evaluation of the routes the distance objective chose.",
    ])

    chunks.append(Chunk(
        id="run:energy",
        kind="solver",
        title="Solver run: energy loss and monetary loss for both routes",
        locator="POST /solve/compare - current run, energy",
        text=text,
        metadata={"lower_loss_route": energy.get("lower_loss_route"),
                  "tariff_inr_per_kwh": tariff.get("inr_per_kwh")},
    ))
    return chunks
