"""The API must never reach IBM Quantum hardware.

Phase 2 keeps a working IBM path and its credentials; Phase 3 simply never
selects it. These tests hold that line, so a future change cannot start
submitting jobs by accident.
"""

from tests.conftest import FAST_HYBRID, START


def test_execution_mode_is_fixed_to_the_simulator():
    from app.services import solver

    assert solver.EXECUTION_MODE == "simulator"


def test_building_an_ibm_runner_would_fail_the_run(client, monkeypatch):
    """Poison the IBM runner: a passing hybrid run proves it was never built."""
    import phase2.backends as backends

    def refuse(*args, **kwargs):
        raise AssertionError("the API must never construct an IBM runner")

    monkeypatch.setattr(backends, "IBMRunner", refuse)

    response = client.post("/solve/hybrid", json={"start": START, **FAST_HYBRID})
    assert response.status_code == 200
    assert response.json()["detail"]["mode"] == "simulator"


def test_a_request_cannot_switch_the_mode(client):
    """An unexpected `mode` field is ignored, not honoured."""
    response = client.post(
        "/solve/hybrid", json={"start": START, "mode": "ibm", **FAST_HYBRID}
    )
    assert response.status_code == 200

    detail = response.json()["detail"]
    assert detail["mode"] == "simulator"
    assert "aer" in detail["backend"].lower()


def test_no_ibm_credentials_are_exposed_by_the_api(client):
    """Nothing in the public surface should echo a token or its variable name."""
    for path in ("/", "/health", "/dataset/status", "/network", "/graphs"):
        body = client.get(path).text.lower()
        assert "ibm_quantum_api_key" not in body
        assert "token" not in body
