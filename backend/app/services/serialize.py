"""Turn Phase 1 / Phase 2 result objects into the API's response models.

Pure reshaping: no value is recomputed, rounded or reinterpreted here.
"""

from __future__ import annotations

from energy_cost.tariff import HOURS_PER_YEAR

from app.schemas.energy import (EnergyTableRowOut, LineUsageOut,
                                RouteEnergyComparisonOut, RouteEnergyOut,
                                TariffOut, UnmatchedStepOut)
from app.schemas.network import (NetworkSummaryOut, StationOut,
                                 TransmissionLineOut)
from app.schemas.solver import (CheckOut, ClassicalSolveOut, ComparisonOut,
                                GraphsOut, HybridDetailOut, HybridSolveOut,
                                LegOut, TableRowOut, TourOut)
from app.services.solver import GRAPH_FILES, station_degree


def checks_out(checks) -> list:
    return [CheckOut(label=label, passed=passed) for label, passed in checks]


def station_out(network, name: str) -> StationOut:
    station = network.stations[name]
    return StationOut(
        name=station.name,
        type=station.type_label,
        latitude=station.latitude,
        longitude=station.longitude,
        connections=station_degree(network, name),
    )


def stations_out(network) -> list:
    return [station_out(network, name) for name in network.names]


def lines_out(network) -> list:
    return [
        TransmissionLineOut(
            source=edge.a,
            destination=edge.b,
            distance_km=edge.distance_km,
            voltage_kv=edge.voltage_kv,
            capacity_mw=edge.capacity_mw,
            loss_percent=edge.loss_percent,
            energy_loss_mw=edge.energy_loss_mw,
        )
        for edge in sorted(network.edges.values(), key=lambda e: (e.a, e.b))
    ]


def summary_out(network) -> NetworkSummaryOut:
    summary = network.summary()
    return NetworkSummaryOut(connected=network.is_connected, **summary)


def tour_out(result, checks) -> TourOut:
    return TourOut(
        start=result.start,
        order=list(result.order),
        closed_route=list(result.closed_route),
        total_distance_km=result.total_distance_km,
        execution_time_s=result.execution_time_s,
        stations_visited=result.stations_visited,
        direct_legs=result.direct_legs,
        legs=[
            LegOut(
                step=leg.step,
                origin=leg.origin,
                destination=leg.destination,
                distance_km=leg.distance_km,
                is_direct=leg.is_direct,
                via=list(leg.via),
            )
            for leg in result.legs
        ],
        valid=all(passed for _, passed in checks),
        checks=checks_out(checks),
    )


def classical_out(start: str, result, checks) -> ClassicalSolveOut:
    return ClassicalSolveOut(start=start, tour=tour_out(result, checks))


def hybrid_out(start: str, hybrid_result, checks) -> HybridSolveOut:
    return HybridSolveOut(
        start=start,
        tour=tour_out(hybrid_result.tour, checks),
        detail=HybridDetailOut(
            mode=hybrid_result.mode,
            backend=hybrid_result.backend_description,
            window=hybrid_result.window,
            qubits_per_subproblem=hybrid_result.qubits_per_subproblem,
            sweeps_run=hybrid_result.sweeps_run,
            subproblems_solved=hybrid_result.subproblems_solved,
            subproblems_skipped=hybrid_result.subproblems_skipped,
            improvements_accepted=hybrid_result.improvements_accepted,
            qaoa_evaluations=hybrid_result.qaoa_evaluations,
            start_distance_km=hybrid_result.start_distance_km,
        ),
    )


def comparison_out(comparison, problem_checks) -> ComparisonOut:
    return ComparisonOut(
        start=comparison.start,
        stations=comparison.stations,
        lines=comparison.lines,
        dataset_path=comparison.dataset_path,
        nn_distance_km=comparison.nn_distance_display,
        nn_time_s=comparison.nn_time_s,
        nn_valid=comparison.nn_valid,
        hybrid_distance_km=comparison.hybrid_distance_display,
        hybrid_time_s=comparison.hybrid_time_s,
        hybrid_valid=comparison.hybrid_valid,
        improvement_km=comparison.improvement_km,
        improvement_percent=comparison.improvement_percent,
        winner=comparison.winner,
        table_rows=[
            TableRowOut(label=label, classical=classical, hybrid=hybrid)
            for label, classical, hybrid in comparison.table_rows()
        ],
        framing_note=comparison.framing_note(),
        same_problem_checks=checks_out(problem_checks),
    )


def graphs_out(outputs_dir: str, paths: dict) -> GraphsOut:
    return GraphsOut(
        outputs_dir=outputs_dir,
        nn_route=paths.get("nn_route"),
        qaoa_route=paths.get("qaoa_route"),
        comparison=paths.get("comparison"),
        urls={name: f"/graphs/{name}" for name in GRAPH_FILES if name in paths},
    )


# ------------------------------------------------------- route energy loss ---
#
# Reshaping only, like everything above. The route -> lines -> loss -> money
# chain is computed in `energy_cost`; nothing is summed or priced here.


def tariff_out(tariff) -> TariffOut:
    return TariffOut(**tariff.provenance())


def line_usage_out(line) -> LineUsageOut:
    return LineUsageOut(
        source=line.source,
        destination=line.destination,
        distance_km=line.distance_km,
        loss_percent=line.loss_percent,
        energy_loss_mw=line.energy_loss_mw,
        traversals=line.traversals,
        loss_cost_per_hour_inr=line.loss_cost_per_hour_inr,
        loss_cost_per_year_inr=line.loss_cost_per_year_inr,
    )


def route_energy_out(route) -> RouteEnergyOut:
    return RouteEnergyOut(
        label=route.label,
        start=route.start,
        total_distance_km=route.total_distance_km,
        line_count=route.line_count,
        traversal_count=route.traversal_count,
        revisited_lines=route.revisited_lines,
        total_energy_loss_mw=route.total_energy_loss_mw,
        total_energy_loss_kwh_per_hour=route.total_energy_loss_kwh_per_hour,
        traversal_energy_loss_mw=route.traversal_energy_loss_mw,
        loss_cost_per_hour_inr=route.loss_cost_per_hour_inr,
        loss_cost_per_year_inr=route.loss_cost_per_year_inr,
        complete=route.is_complete,
        lines_missing_loss=[line_usage_out(l) for l in route.lines_missing_loss],
        unmatched_steps=[
            UnmatchedStepOut(
                leg_step=step.leg_step,
                origin=step.origin,
                destination=step.destination,
                reason=step.reason,
            )
            for step in route.unmatched_steps
        ],
        lines_used=[line_usage_out(l) for l in route.lines_used],
        caveats=route.caveats(),
    )


ANNUALISATION_NOTE = (
    "Annualised cost = hourly cost x 8,760, i.e. it assumes the modeled loss "
    "is present continuously for every hour of the year. The dataset carries "
    "no load factor or operating profile, so this is an ESTIMATE - not an "
    "actual yearly loss and not an electricity bill."
)


def route_energy_comparison_out(comparison) -> RouteEnergyComparisonOut:
    return RouteEnergyComparisonOut(
        tariff=tariff_out(comparison.tariff),
        classical=route_energy_out(comparison.classical),
        hybrid=route_energy_out(comparison.hybrid),
        distance_difference_km=comparison.distance_difference_km,
        energy_loss_difference_mw=comparison.energy_loss_difference_mw,
        hourly_cost_difference_inr=comparison.hourly_cost_difference_inr,
        annual_cost_difference_inr=comparison.annual_cost_difference_inr,
        lower_loss_route=comparison.lower_loss_route,
        hours_per_year=HOURS_PER_YEAR,
        annualisation_note=ANNUALISATION_NOTE,
        table_rows=[
            EnergyTableRowOut(label=label, classical=classical, hybrid=hybrid)
            for label, classical, hybrid in comparison.table_rows()
        ],
        framing_note=comparison.framing_note(),
    )
