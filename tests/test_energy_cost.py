"""Tests for the route energy-loss costing.

Three things are being protected here:

  1. The arithmetic. MW -> kWh, hourly cost, annualised cost: small, exact,
     checkable by hand.
  2. The mapping from a route to real transmission lines, including the awkward
     cases - legs that traverse several lines, lines crossed twice, lines with
     no Energy_Loss_MW, and steps that match no line at all.
  3. That this feature changed nothing it was not supposed to. The dataset
     still holds 26 stations and 38 lines, and the Nearest Neighbour tour is
     the same tour it was before any of this existed.
"""

from __future__ import annotations

import math

import pytest

from energy_cost import (compare_routes, route_energy_loss)
from energy_cost.recompute import DERIVED_COLUMNS, derived_cells, rewrite
from energy_cost.tariff import (HOURS_PER_YEAR,
                                KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE,
                                TariffRate, annualised_cost_inr,
                                hourly_cost_inr, mw_to_kwh_per_hour,
                                resolve_tariff)
from phase1.data_loader import load_dataset
from phase1.network import Network
from phase1.nn_tsp import Leg, TourResult
from phase1.nn_tsp import solve as nn_solve

START = "Mysuru Substation"
# A second, different start, to get a second route without the QAOA simulator.
OTHER_START = "Kaiga Nuclear Power Station"
TARIFF = KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


@pytest.fixture(scope="module")
def network(dataset):
    return Network(dataset)


@pytest.fixture(scope="module")
def nn_route(network):
    return nn_solve(network, START)


# --------------------------------------------------------------- the tariff --

def test_tariff_is_the_verified_kerc_ht_industrial_energy_charge():
    """The rate, and the provenance that makes it checkable."""
    assert TARIFF.inr_per_kwh == 6.60
    assert TARIFF.paise_per_kwh == 660
    assert "Karnataka Electricity Regulatory Commission" in TARIFF.authority
    assert TARIFF.order_date == "2025-03-27"
    assert "HT-2(a)" in TARIFF.category
    assert "kerc.karnataka.gov.in" in TARIFF.source_url


def test_tariff_is_energy_charge_only():
    """The excluded components are named, not merely implied."""
    assert "Energy Charges" in TARIFF.component
    excluded = " ".join(TARIFF.excludes).lower()
    for component in ("demand charge", "fixed charge", "fppca", "tax"):
        assert component in excluded


def test_the_rs_3_figure_is_not_used_anywhere():
    """Rs. 3.00/kWh did not survive checking against the order."""
    assert TARIFF.inr_per_kwh != 3.00


def test_resolve_tariff_defaults_to_the_verified_rate():
    assert resolve_tariff(None) is TARIFF
    other = TariffRate(
        inr_per_kwh=1.0, order_name="x", authority="x", order_date="x",
        effective_period="x", category="x", component="x", source_url="x",
        source_location="x", accessed="x", excludes=(),
    )
    assert resolve_tariff(other) is other


# ------------------------------------------------------------- the arithmetic

def test_mw_to_kwh_per_hour():
    """1 MW held for an hour is 1000 kWh."""
    assert mw_to_kwh_per_hour(1.0) == 1000.0
    assert mw_to_kwh_per_hour(0.0) == 0.0
    assert mw_to_kwh_per_hour(2.5) == 2500.0


def test_hourly_loss_cost():
    """Loss_Cost_Per_Hour_INR = MW x 1000 x tariff."""
    # 1 MW for an hour is 1000 kWh; at Rs. 6.60/kWh that is Rs. 6,600.
    assert hourly_cost_inr(1.0) == pytest.approx(6600.0)
    assert hourly_cost_inr(0.0) == 0.0
    assert hourly_cost_inr(10.0) == pytest.approx(66000.0)


def test_hourly_loss_cost_honours_a_supplied_tariff():
    rate = TariffRate(
        inr_per_kwh=2.0, order_name="x", authority="x", order_date="x",
        effective_period="x", category="x", component="x", source_url="x",
        source_location="x", accessed="x", excludes=(),
    )
    assert hourly_cost_inr(3.0, rate) == pytest.approx(6000.0)


def test_annualised_loss_cost():
    """Loss_Cost_Per_Year_INR = hourly x 8760."""
    assert HOURS_PER_YEAR == 8760
    assert annualised_cost_inr(1.0) == 8760.0
    assert annualised_cost_inr(hourly_cost_inr(1.0)) == pytest.approx(6600.0 * 8760)


def test_the_two_formulas_compose():
    """A megawatt of loss, all the way through, by hand."""
    loss_mw = 12.5
    hourly = loss_mw * 1000 * 6.60
    assert hourly_cost_inr(loss_mw) == pytest.approx(hourly)
    assert annualised_cost_inr(hourly_cost_inr(loss_mw)) == pytest.approx(hourly * 8760)


# --------------------------------------------------- route-level aggregation

def test_route_loss_sums_the_datasets_own_values(network, nn_route):
    """The total is the sum of Energy_Loss_MW over the distinct lines used."""
    route = route_energy_loss(network, nn_route, "Classical NN")

    by_hand = sum(
        line.energy_loss_mw for line in route.lines_used
        if line.energy_loss_mw is not None
    )
    assert route.total_energy_loss_mw == pytest.approx(by_hand)
    assert route.loss_cost_per_hour_inr == pytest.approx(
        route.total_energy_loss_mw * 1000 * TARIFF.inr_per_kwh
    )
    assert route.loss_cost_per_year_inr == pytest.approx(
        route.loss_cost_per_hour_inr * HOURS_PER_YEAR
    )


def test_route_lines_are_real_dataset_lines(network, nn_route):
    """Every line the analysis reports exists in the network, with its own values."""
    route = route_energy_loss(network, nn_route)
    assert route.lines_used

    for line in route.lines_used:
        edge = network.edge_between(line.source, line.destination)
        assert edge is not None
        assert line.distance_km == edge.distance_km
        assert line.loss_percent == edge.loss_percent
        assert line.energy_loss_mw == edge.energy_loss_mw


def test_route_uses_no_more_lines_than_the_network_has(network, nn_route):
    route = route_energy_loss(network, nn_route)
    assert 0 < route.line_count <= len(network.edges)


def test_a_multi_line_leg_is_expanded_into_its_lines(network, nn_route):
    """A leg routed through pass-through stations contributes each hop.

    This is the case the mapping exists for: a leg is not a transmission line,
    so the traversal count exceeds the number of legs whenever the tour is
    routed over the shortest-path closure.
    """
    route = route_energy_loss(network, nn_route)
    indirect = [leg for leg in nn_route.legs if not leg.is_direct]
    assert indirect, "the sparse network should force at least one indirect leg"

    hops = sum(len(leg.path) - 1 for leg in nn_route.legs)
    assert route.traversal_count == hops
    assert route.traversal_count > len(nn_route.legs)


def test_a_line_crossed_twice_is_counted_once(network):
    """Energy_Loss_MW is steady-state, so re-crossing must not double it."""
    edge = next(iter(network.edges.values()))
    a, b = edge.a, edge.b

    # Out and straight back: the same physical line, twice.
    there_and_back = TourResult(
        start=a,
        order=[a, b],
        legs=[
            Leg(1, a, b, edge.distance_km, [a, b], True),
            Leg(2, b, a, edge.distance_km, [b, a], True),
        ],
        total_distance_km=edge.distance_km * 2,
        execution_time_s=0.0,
        stations_visited=2,
    )

    route = route_energy_loss(network, there_and_back)
    assert route.line_count == 1
    assert route.traversal_count == 2
    assert route.revisited_lines == 1
    assert route.lines_used[0].traversals == 2
    # Counted once in the headline, twice in the transparency figure.
    assert route.total_energy_loss_mw == pytest.approx(edge.energy_loss_mw)
    assert route.traversal_energy_loss_mw == pytest.approx(edge.energy_loss_mw * 2)


def test_distance_does_not_determine_loss(network, nn_route):
    """Loss is read off the lines, never derived from how far the route runs."""
    route = route_energy_loss(network, nn_route)
    assert route.total_distance_km == nn_route.total_distance_km

    # A line's loss is not a fixed multiple of its length across the dataset,
    # so no length-based rule could have produced these totals.
    ratios = {
        round(line.energy_loss_mw / line.distance_km, 6)
        for line in route.lines_used
        if line.energy_loss_mw is not None and line.distance_km
    }
    assert len(ratios) > 1


def test_the_full_route_is_complete_on_this_dataset(network, nn_route):
    route = route_energy_loss(network, nn_route)
    assert route.lines_missing_loss == []
    assert route.unmatched_steps == []
    assert route.is_complete


# ---------------------------------------------- missing and unmatched legs --

def test_a_line_without_energy_loss_contributes_nothing_and_is_reported(network):
    """A blank Energy_Loss_MW is never filled in with a guess."""
    edge = next(iter(network.edges.values()))
    a, b = edge.a, edge.b
    original = edge.energy_loss_mw
    edge.energy_loss_mw = None
    try:
        hop = TourResult(
            start=a, order=[a, b],
            legs=[Leg(1, a, b, edge.distance_km, [a, b], True)],
            total_distance_km=edge.distance_km,
            execution_time_s=0.0, stations_visited=2,
        )
        route = route_energy_loss(network, hop)

        assert route.total_energy_loss_mw == 0.0
        assert route.loss_cost_per_hour_inr == 0.0
        assert len(route.lines_missing_loss) == 1
        assert route.lines_missing_loss[0].loss_cost_per_hour_inr is None
        assert route.lines_missing_loss[0].loss_cost_per_year_inr is None
        assert not route.is_complete
        assert any("lower bound" in note for note in route.caveats())
    finally:
        edge.energy_loss_mw = original


def test_a_step_matching_no_line_is_reported_not_priced(network):
    """An unroutable pair is recorded as unmatched rather than costed."""
    names = network.names
    unlinked = next(
        (a, b)
        for a in names for b in names
        if a != b and network.edge_between(a, b) is None
    )
    a, b = unlinked

    bogus = TourResult(
        start=a, order=[a, b],
        legs=[Leg(1, a, b, 1.0, [a, b], False)],
        total_distance_km=1.0, execution_time_s=0.0, stations_visited=2,
    )
    route = route_energy_loss(network, bogus)

    assert route.lines_used == []
    assert route.total_energy_loss_mw == 0.0
    assert len(route.unmatched_steps) == 1
    assert route.unmatched_steps[0].origin == a
    assert route.unmatched_steps[0].destination == b
    assert not route.is_complete


def test_a_leg_with_no_recorded_path_is_reported_not_priced(network):
    """A leg that records no traversal maps to no line, and says so."""
    names = network.names
    a, b = names[0], names[1]
    pathless = TourResult(
        start=a, order=[a, b],
        legs=[Leg(1, a, b, 1.0, [], False)],
        total_distance_km=1.0, execution_time_s=0.0, stations_visited=2,
    )
    route = route_energy_loss(network, pathless)

    assert route.lines_used == []
    assert len(route.unmatched_steps) == 1
    assert "no traversed path" in route.unmatched_steps[0].reason


# ------------------------------------------------------ NN vs Hybrid QAOA --

def test_comparison_costs_both_routes_at_the_same_tariff(network, nn_route):
    """Both sides priced identically is what makes the difference meaningful."""
    # A second tour from a different start stands in for the hybrid one here:
    # `compare_routes` only needs two TourResults on the same network, and this
    # keeps the test off the slow QAOA simulator. The API test exercises the
    # genuine hybrid result.
    other = nn_solve(network, OTHER_START)
    comparison = compare_routes(network, nn_route, other)

    assert comparison.tariff is TARIFF
    assert comparison.classical.tariff is TARIFF
    assert comparison.hybrid.tariff is TARIFF
    assert comparison.classical.label == "Classical NN"
    assert comparison.hybrid.label == "Hybrid QAOA"


def test_comparison_differences_are_classical_minus_hybrid(network, nn_route):
    other = nn_solve(network, OTHER_START)
    comparison = compare_routes(network, nn_route, other)

    assert comparison.distance_difference_km == pytest.approx(
        comparison.classical.total_distance_km - comparison.hybrid.total_distance_km
    )
    assert comparison.energy_loss_difference_mw == pytest.approx(
        comparison.classical.total_energy_loss_mw
        - comparison.hybrid.total_energy_loss_mw
    )
    assert comparison.hourly_cost_difference_inr == pytest.approx(
        comparison.classical.loss_cost_per_hour_inr
        - comparison.hybrid.loss_cost_per_hour_inr
    )
    assert comparison.annual_cost_difference_inr == pytest.approx(
        comparison.hourly_cost_difference_inr * HOURS_PER_YEAR
    )


def test_lower_loss_route_names_the_right_side(network, nn_route):
    other = nn_solve(network, OTHER_START)
    comparison = compare_routes(network, nn_route, other)
    difference = comparison.energy_loss_difference_mw

    if abs(difference) < 1e-9:
        assert comparison.lower_loss_route == "tie"
    elif difference > 0:
        assert comparison.lower_loss_route == "hybrid"
    else:
        assert comparison.lower_loss_route == "classical"


def test_identical_routes_tie(network, nn_route):
    comparison = compare_routes(network, nn_route, nn_route)
    assert comparison.energy_loss_difference_mw == 0.0
    assert comparison.hourly_cost_difference_inr == 0.0
    assert comparison.lower_loss_route == "tie"


def test_comparison_accepts_a_hybrid_result_wrapper(network, nn_route):
    """`compare_routes` unwraps a HybridResult-shaped object."""

    class FakeHybridResult:
        def __init__(self, tour):
            self.tour = tour

    comparison = compare_routes(network, nn_route, FakeHybridResult(nn_route))
    assert comparison.hybrid.total_energy_loss_mw == pytest.approx(
        comparison.classical.total_energy_loss_mw
    )


def test_comparison_table_states_every_required_figure(network, nn_route):
    other = nn_solve(network, OTHER_START)
    rows = compare_routes(network, nn_route, other).table_rows()
    labels = [label for label, _, _ in rows]

    assert "Total route distance" in labels
    assert "Modeled energy loss" in labels
    assert "Estimated loss cost / hour" in labels
    assert "Annualised loss cost (estimate)" in labels
    assert all(len(row) == 3 for row in rows)


# ---------------------------------------------------------------- caveats --

def test_caveats_flag_the_annualisation_assumption(network, nn_route):
    notes = " ".join(route_energy_loss(network, nn_route).caveats()).lower()
    assert "8,760" in notes
    assert "estimate" in notes
    assert "not an electricity bill" in notes
    assert "energy charge only" in notes


def test_framing_note_says_this_is_not_an_optimization_objective(network, nn_route):
    other = nn_solve(network, OTHER_START)
    note = compare_routes(network, nn_route, other).framing_note().lower()
    assert "distance_km" in note
    assert "not part of either cost function" in note


# ------------------------------------------------- the derived CSV columns --

def test_derived_cells_follow_the_formulas():
    hourly, yearly = derived_cells(10.0, TARIFF)
    assert float(hourly) == pytest.approx(10.0 * 1000 * 6.60)
    assert float(yearly) == pytest.approx(float(hourly) * 8760)


def test_derived_cells_stay_blank_without_a_source_value():
    """A blank Energy_Loss_MW yields blanks, never a substituted number."""
    assert derived_cells(None, TARIFF) == ("", "")


def test_the_csv_derived_columns_are_current(dataset):
    """The CSV's calculated columns match what the current tariff produces.

    This is what stops the columns drifting silently after a tariff change.
    """
    report = rewrite(dataset.path, TARIFF, write=False)
    assert report["already_current"], (
        "data CSV derived columns are stale - run "
        "`python -m energy_cost.recompute`"
    )


def test_the_csv_derived_columns_match_each_row(dataset):
    frame = dataset.raw
    for column in DERIVED_COLUMNS:
        assert column in frame.columns

    for _, row in frame.iterrows():
        loss = row["Energy_Loss_MW"]
        if loss is None or (isinstance(loss, float) and math.isnan(loss)):
            continue
        assert row["Loss_Cost_Per_Hour_INR"] == pytest.approx(
            hourly_cost_inr(float(loss)), rel=1e-9, abs=0.01
        )
        assert row["Loss_Cost_Per_Year_INR"] == pytest.approx(
            annualised_cost_inr(hourly_cost_inr(float(loss))), rel=1e-9, abs=1.0
        )


# -------------------------------------------------------- nothing regressed --

def test_the_dataset_still_holds_26_stations_and_38_lines(dataset, network):
    assert len(dataset.stations) == 26
    assert len(dataset.connections) == 38
    assert len(network.edges) == 38
    assert network.is_connected


def test_the_added_columns_did_not_disturb_the_source_columns(dataset):
    """Every column Phase 1 reads is still there, ahead of the derived pair."""
    columns = list(dataset.raw.columns)
    expected = [
        "Source", "Destination", "Type",
        "Source_Latitude", "Source_Longitude",
        "Destination_Latitude", "Destination_Longitude",
        "Distance_km", "Voltage_kV", "Capacity_MW",
        "Loss_Percent", "Energy_Loss_MW",
    ]
    assert columns[:len(expected)] == expected
    assert columns[len(expected):] == list(DERIVED_COLUMNS)
    assert dataset.warnings == []


def test_the_nearest_neighbour_tour_is_unchanged(network, nn_route):
    """The recorded NN result for this dataset and start, to 3 decimals.

    If costing the route ever changed the route, this fails.
    """
    assert nn_route.total_distance_km == pytest.approx(3017.795, abs=5e-4)
    assert nn_route.start == START
    assert nn_route.stations_visited == 26
    assert len(nn_route.legs) == 26
    assert nn_route.closed_route[-1] == START


def test_costing_a_route_does_not_mutate_it(network, nn_route):
    before = (
        list(nn_route.order),
        nn_route.total_distance_km,
        [(leg.origin, leg.destination, leg.distance_km) for leg in nn_route.legs],
    )
    route_energy_loss(network, nn_route)
    after = (
        list(nn_route.order),
        nn_route.total_distance_km,
        [(leg.origin, leg.destination, leg.distance_km) for leg in nn_route.legs],
    )
    assert before == after
