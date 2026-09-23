"""The solver endpoints.

These assert that the API returns what the existing solvers return - not that
the solvers are correct, which the Phase 1 and Phase 2 suites already cover.
"""

import pytest

from tests.conftest import FAST_HYBRID, START


def test_classical_matches_the_phase_1_solver(client):
    """The endpoint must return Phase 1's own answer, not a second solver."""
    from phase1.nn_tsp import solve

    from app.dataio.network import get_network

    expected = solve(get_network(), START)
    body = client.post("/solve/classical", json={"start": START}).json()
    tour = body["tour"]

    assert body["algorithm"] == "classical-nearest-neighbour"
    assert tour["total_distance_km"] == pytest.approx(
        expected.total_distance_km
    )
    assert tour["order"] == list(expected.order)
    assert tour["closed_route"] == list(expected.closed_route)


def test_classical_returns_a_valid_twenty_six_station_tour(client):
    tour = client.post("/solve/classical", json={"start": START}).json()["tour"]

    assert tour["stations_visited"] == 26
    assert len(tour["order"]) == 26
    assert len(tour["closed_route"]) == 27
    assert tour["closed_route"][0] == tour["closed_route"][-1] == START
    assert len(tour["legs"]) == 26
    assert tour["valid"] is True
    assert all(check["passed"] for check in tour["checks"])


def test_classical_rejects_an_invalid_start(client):
    response = client.post("/solve/classical", json={"start": "Nowhere"})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unknown_start_station"


def test_classical_requires_a_start(client):
    assert client.post("/solve/classical", json={}).status_code == 422


def test_hybrid_runs_on_the_simulator(client):
    response = client.post("/solve/hybrid", json={"start": START, **FAST_HYBRID})
    assert response.status_code == 200

    body = response.json()
    assert body["algorithm"] == "hybrid-qaoa-reoptimization"
    assert body["detail"]["mode"] == "simulator"
    assert "aer" in body["detail"]["backend"].lower()
    assert body["detail"]["window"] == FAST_HYBRID["window"]
    assert body["detail"]["qubits_per_subproblem"] == FAST_HYBRID["window"] ** 2


def test_hybrid_returns_a_valid_twenty_six_station_tour(client):
    tour = client.post(
        "/solve/hybrid", json={"start": START, **FAST_HYBRID}
    ).json()["tour"]

    assert tour["stations_visited"] == 26
    assert sorted(tour["order"]) == sorted(set(tour["order"]))
    assert len(tour["closed_route"]) == 27
    assert tour["closed_route"][0] == tour["closed_route"][-1] == START
    assert tour["valid"] is True


def test_hybrid_never_lengthens_the_classical_tour(client, compared):
    """The reoptimizer only accepts improvements, so it cannot do worse."""
    assert (compared["hybrid"]["tour"]["total_distance_km"]
            <= compared["classical"]["tour"]["total_distance_km"] + 1e-9)


def test_hybrid_rejects_an_invalid_start(client):
    response = client.post(
        "/solve/hybrid", json={"start": "Nowhere", **FAST_HYBRID}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unknown_start_station"


def test_hybrid_rejects_out_of_range_options(client):
    response = client.post("/solve/hybrid", json={"start": START, "window": 99})
    assert response.status_code == 422


def test_compare_returns_both_solvers_and_the_comparison(compared):
    assert compared["start"] == START
    assert compared["classical"]["tour"]["stations_visited"] == 26
    assert compared["hybrid"]["tour"]["stations_visited"] == 26

    comparison = compared["comparison"]
    assert comparison["stations"] == 26
    assert comparison["lines"] == 38
    assert comparison["nn_valid"] is True
    assert comparison["hybrid_valid"] is True
    assert comparison["winner"] in {"hybrid", "classical", "tie"}


def test_compare_difference_is_recomputable_from_the_returned_distances(compared):
    """Same consistency rule the terminal and the figure follow."""
    comparison = compared["comparison"]
    nn = comparison["nn_distance_km"]
    hybrid = comparison["hybrid_distance_km"]

    assert comparison["improvement_km"] == pytest.approx(round(nn - hybrid, 3))
    assert comparison["improvement_percent"] == pytest.approx(
        round(comparison["improvement_km"] / nn * 100.0, 2)
    )


def test_compare_confirms_both_solvers_got_the_same_problem(compared):
    checks = compared["comparison"]["same_problem_checks"]
    assert checks
    assert all(check["passed"] for check in checks)

    classical_route = compared["classical"]["tour"]["closed_route"]
    hybrid_route = compared["hybrid"]["tour"]["closed_route"]
    assert sorted(classical_route[:-1]) == sorted(hybrid_route[:-1])
    assert classical_route[0] == hybrid_route[0] == START


def test_compare_never_claims_quantum_advantage(compared):
    note = compared["comparison"]["framing_note"].lower()
    assert "no quantum advantage" in note


def test_compare_can_skip_rendering(compared):
    assert compared["graphs"]["nn_route"] is None
    assert compared["graphs"]["comparison"] is None
