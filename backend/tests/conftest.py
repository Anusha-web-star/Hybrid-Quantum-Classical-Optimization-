"""Shared fixtures for the backend tests.

The hybrid endpoints run the real QAOA simulator, so the tests that call them
use a small window and a single sweep. That is a speed setting, not a different
algorithm: the same `phase2.hybrid.hybrid_solve` runs either way.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.main import app

START = "Mysuru Substation"

# A deliberately quick hybrid run: 9-qubit subproblems, one sweep.
FAST_HYBRID = {"window": 3, "sweeps": 1, "maxiter": 8, "shots": 512, "seed": 7}


@pytest.fixture(scope="session")
def client():
    """Client for the functional (solver/dataset) tests.

    These tests exercise the optimization endpoints, not authentication, so the
    auth dependency is overridden with a fixed test user. That keeps them
    focused and unbroken by the new gate. The genuine token-verification path is
    tested separately, without this override, in test_auth.py.
    """
    app.dependency_overrides[require_user] = lambda: AuthUser(
        {"sub": "test-user", "email": "tester@gridopt.local", "aud": "authenticated"}
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def outputs_dir(tmp_path_factory):
    """Point the API's outputs folder at a temp directory.

    Keeps the tests from overwriting the real `outputs/` images, which are
    produced by a full-length run and should not be replaced by a fast one.
    """
    target = tmp_path_factory.mktemp("outputs")
    previous = os.environ.get("OUTPUTS_DIR")
    os.environ["OUTPUTS_DIR"] = str(target)
    get_settings.cache_clear()
    try:
        yield target
    finally:
        if previous is None:
            os.environ.pop("OUTPUTS_DIR", None)
        else:
            os.environ["OUTPUTS_DIR"] = previous
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def compared(client):
    """One hybrid comparison run, shared by the tests that need it."""
    response = client.post(
        "/solve/compare",
        json={"start": START, "render_graphs": False, **FAST_HYBRID},
    )
    assert response.status_code == 200, response.text
    return response.json()
