"""The route energy-loss costing, as `/solve/compare` returns it.

These run against the genuine hybrid result, so they check the thing the
dashboard actually receives: both real tours, costed on the same network at the
same tariff, with the provenance attached.

They reuse the session-scoped `compared` fixture, so no extra QAOA run is paid
for here.
"""

HOURS_PER_YEAR = 8760
TARIFF_INR_PER_KWH = 6.60


def energy(compared):
    return compared["energy"]


# ------------------------------------------------------------- the tariff --

def test_the_tariff_is_the_verified_kerc_rate(compared):
    tariff = energy(compared)["tariff"]
    assert tariff["inr_per_kwh"] == TARIFF_INR_PER_KWH
    assert tariff["paise_per_kwh"] == 660
    assert "HT-2(a)" in tariff["category"]
    assert "Karnataka Electricity Regulatory Commission" in tariff["authority"]
    assert tariff["order_date"] == "2025-03-27"
    assert tariff["source_url"].startswith("https://kerc.karnataka.gov.in/")
    assert tariff["accessed"]


def test_the_response_says_it_is_energy_charge_only(compared):
    tariff = energy(compared)["tariff"]
    assert "Energy Charges" in tariff["component"]

    excluded = " ".join(tariff["excludes"]).lower()
    for component in ("demand charge", "fixed charge", "fppca", "tax"):
        assert component in excluded


# ---------------------------------------------------------- both routes ----

def test_both_routes_are_costed(compared):
    block = energy(compared)
    for side in ("classical", "hybrid"):
        route = block[side]
        assert route["line_count"] > 0
        assert route["total_energy_loss_mw"] > 0
        assert route["loss_cost_per_hour_inr"] > 0
        assert route["loss_cost_per_year_inr"] > 0
        assert route["lines_used"]


def test_route_distance_matches_the_tour_it_came_from(compared):
    block = energy(compared)
    assert block["classical"]["total_distance_km"] == (
        compared["classical"]["tour"]["total_distance_km"]
    )
    assert block["hybrid"]["total_distance_km"] == (
        compared["hybrid"]["tour"]["total_distance_km"]
    )


def test_hourly_cost_follows_the_stated_formula(compared):
    """MW x 1000 x tariff, recomputable from the numbers returned."""
    for side in ("classical", "hybrid"):
        route = energy(compared)[side]
        expected = route["total_energy_loss_mw"] * 1000 * TARIFF_INR_PER_KWH
        assert abs(route["loss_cost_per_hour_inr"] - expected) < 1e-6
        assert route["total_energy_loss_kwh_per_hour"] == (
            route["total_energy_loss_mw"] * 1000
        )


def test_annualised_cost_is_the_hourly_cost_times_8760(compared):
    block = energy(compared)
    assert block["hours_per_year"] == HOURS_PER_YEAR
    for side in ("classical", "hybrid"):
        route = block[side]
        expected = route["loss_cost_per_hour_inr"] * HOURS_PER_YEAR
        assert abs(route["loss_cost_per_year_inr"] - expected) < 1e-3


def test_route_loss_is_the_sum_of_the_lines_it_lists(compared):
    """The total can be rebuilt from the per-line rows in the same response."""
    for side in ("classical", "hybrid"):
        route = energy(compared)[side]
        by_line = sum(
            line["energy_loss_mw"] for line in route["lines_used"]
            if line["energy_loss_mw"] is not None
        )
        assert abs(route["total_energy_loss_mw"] - by_line) < 1e-9


def test_lines_used_are_real_transmission_lines(client, compared):
    """Every costed line appears in the network the API serves."""
    network = client.get("/network").json()
    known = {
        tuple(sorted((line["source"], line["destination"])))
        for line in network["transmission_lines"]
    }

    for side in ("classical", "hybrid"):
        for line in energy(compared)[side]["lines_used"]:
            assert tuple(sorted((line["source"], line["destination"]))) in known


def test_a_line_crossed_twice_is_still_counted_once(compared):
    """Traversals may exceed the distinct-line count; the loss total may not."""
    for side in ("classical", "hybrid"):
        route = energy(compared)[side]
        assert route["traversal_count"] >= route["line_count"]
        assert route["revisited_lines"] == sum(
            1 for line in route["lines_used"] if line["traversals"] > 1
        )
        if route["revisited_lines"]:
            assert route["traversal_energy_loss_mw"] > route["total_energy_loss_mw"]
        else:
            assert route["traversal_energy_loss_mw"] == route["total_energy_loss_mw"]


def test_per_line_costs_use_the_lines_own_loss(compared):
    for side in ("classical", "hybrid"):
        for line in energy(compared)[side]["lines_used"]:
            if line["energy_loss_mw"] is None:
                assert line["loss_cost_per_hour_inr"] is None
                assert line["loss_cost_per_year_inr"] is None
                continue
            expected = line["energy_loss_mw"] * 1000 * TARIFF_INR_PER_KWH
            assert abs(line["loss_cost_per_hour_inr"] - expected) < 1e-6


def test_this_dataset_leaves_no_unmatched_or_unpriced_legs(compared):
    """Every leg of both routes maps to lines that carry a loss value."""
    for side in ("classical", "hybrid"):
        route = energy(compared)[side]
        assert route["unmatched_steps"] == []
        assert route["lines_missing_loss"] == []
        assert route["complete"] is True


# --------------------------------------------------------- the comparison --

def test_differences_are_classical_minus_hybrid(compared):
    block = energy(compared)
    nn, qa = block["classical"], block["hybrid"]

    assert abs(block["distance_difference_km"]
               - (nn["total_distance_km"] - qa["total_distance_km"])) < 1e-9
    assert abs(block["energy_loss_difference_mw"]
               - (nn["total_energy_loss_mw"] - qa["total_energy_loss_mw"])) < 1e-9
    assert abs(block["hourly_cost_difference_inr"]
               - (nn["loss_cost_per_hour_inr"] - qa["loss_cost_per_hour_inr"])) < 1e-6
    assert abs(block["annual_cost_difference_inr"]
               - block["hourly_cost_difference_inr"] * HOURS_PER_YEAR) < 1e-3


def test_lower_loss_route_agrees_with_the_difference(compared):
    block = energy(compared)
    difference = block["energy_loss_difference_mw"]
    expected = ("tie" if abs(difference) < 1e-9
                else "hybrid" if difference > 0 else "classical")
    assert block["lower_loss_route"] == expected


def test_the_comparison_table_carries_every_required_row(compared):
    labels = [row["label"] for row in energy(compared)["table_rows"]]
    assert "Total route distance" in labels
    assert "Modeled energy loss" in labels
    assert "Estimated loss cost / hour" in labels
    assert "Annualised loss cost (estimate)" in labels

    for row in energy(compared)["table_rows"]:
        assert row["classical"] and row["hybrid"]


# ----------------------------------------------------------- the framing ---

def test_the_annualisation_assumption_is_stated(compared):
    note = energy(compared)["annualisation_note"].lower()
    assert "8,760" in note
    assert "estimate" in note
    assert "not an electricity bill" in note


def test_every_route_carries_its_caveats(compared):
    for side in ("classical", "hybrid"):
        caveats = " ".join(energy(compared)[side]["caveats"]).lower()
        assert "8,760" in caveats
        assert "energy charge only" in caveats
        assert "distance does not determine loss" in caveats


def test_the_framing_says_loss_is_not_an_optimization_objective(compared):
    note = energy(compared)["framing_note"].lower()
    assert "distance_km" in note
    assert "not part of either cost function" in note


# ------------------------------------------------- nothing else regressed --

def test_the_distance_comparison_is_untouched(compared):
    """Adding the energy block changed no existing figure."""
    comparison = compared["comparison"]
    assert comparison["stations"] == 26
    assert comparison["lines"] == 38
    assert comparison["winner"] in {"hybrid", "classical", "tie"}
    assert all(check["passed"] for check in comparison["same_problem_checks"])
    assert compared["classical"]["tour"]["valid"]
    assert compared["hybrid"]["tour"]["valid"]


def test_the_energy_block_did_not_change_the_routes(compared):
    """Both tours still visit all 26 stations and close."""
    for side in ("classical", "hybrid"):
        tour = compared[side]["tour"]
        assert tour["stations_visited"] == 26
        assert len(set(tour["order"])) == 26
        assert tour["closed_route"][-1] == tour["start"]
