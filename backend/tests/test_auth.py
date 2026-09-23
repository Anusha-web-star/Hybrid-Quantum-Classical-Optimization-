"""Real Supabase-JWT verification tests for the protected API.

These run with AUTH_MODE=supabase. The active default is AUTH_MODE=demo, where
the browser holds the sign-in gate and the API demands no token; that mode has
its own test at the bottom of this file.

These do NOT bypass verification. They mint genuine ES256 tokens with a local
key pair and point the verifier's key lookup at the matching public key, so the
actual production path runs: signature check, audience, issuer, expiry. Only the
*source* of the public key is swapped (a local key instead of a network fetch),
which is exactly what verifying a real Supabase token does, minus the HTTP call.

No `dependency_overrides` are used here - the auth dependency runs for real.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth
from app.core.auth import require_user
from app.core.config import get_settings
from app.main import app

PROJECT_URL = "https://test-project.supabase.co"
ISSUER = f"{PROJECT_URL}/auth/v1"
AUDIENCE = "authenticated"


@pytest.fixture
def es256_keys():
    """A throwaway ES256 key pair for signing test tokens."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def auth_env(monkeypatch, es256_keys):
    """Configure the verifier for the test project and its local public key.

    Removes any auth override left by other fixtures, points config at the test
    project, and makes the signing-key lookup return the local public key rather
    than fetching Supabase's JWKS. Restores everything afterwards.
    """
    _, public_key = es256_keys

    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()

    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", PROJECT_URL)
    monkeypatch.setenv("SUPABASE_JWT_AUD", AUDIENCE)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    get_settings.cache_clear()

    monkeypatch.setattr(auth, "_signing_key", lambda token: public_key)

    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)
        get_settings.cache_clear()


def make_token(private_key, *, sub="user-123", exp_delta=3600,
               aud=AUDIENCE, iss=ISSUER, email="user@example.com"):
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "aud": aud,
        "iss": iss,
        "iat": now,
        "exp": now + exp_delta,
        "role": "authenticated",
    }
    return jwt.encode(payload, private_key, algorithm="ES256")


@pytest.fixture
def real_client(auth_env):
    with TestClient(app) as c:
        yield c


# --- the gate itself -------------------------------------------------------

def test_missing_token_is_rejected(real_client):
    r = real_client.get("/stations")
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "not_authenticated"


def test_garbage_token_is_rejected(real_client):
    r = real_client.get("/stations", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_wrong_scheme_is_rejected(real_client, es256_keys):
    private_key, _ = es256_keys
    token = make_token(private_key)
    r = real_client.get("/stations", headers={"Authorization": f"Basic {token}"})
    assert r.status_code == 401


def test_expired_token_is_rejected(real_client, es256_keys):
    private_key, _ = es256_keys
    token = make_token(private_key, exp_delta=-10)
    r = real_client.get("/stations", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "expired" in r.json()["detail"]["message"].lower()


def test_wrong_audience_is_rejected(real_client, es256_keys):
    private_key, _ = es256_keys
    token = make_token(private_key, aud="anon")
    r = real_client.get("/stations", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_wrong_issuer_is_rejected(real_client, es256_keys):
    private_key, _ = es256_keys
    token = make_token(private_key, iss="https://evil.example.com/auth/v1")
    r = real_client.get("/stations", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_token_signed_by_a_different_key_is_rejected(real_client):
    """A validly-shaped token signed by a key we do not trust must fail."""
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    token = make_token(attacker_key)
    r = real_client.get("/stations", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# --- the happy path --------------------------------------------------------

def test_valid_token_is_accepted(real_client, es256_keys):
    private_key, _ = es256_keys
    token = make_token(private_key)
    r = real_client.get("/stations", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 26
    assert len(body["stations"]) == 26


def test_valid_token_reaches_network(real_client, es256_keys):
    private_key, _ = es256_keys
    token = make_token(private_key)
    r = real_client.get("/network", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["stations"] == 26


# --- what stays open -------------------------------------------------------

def test_health_is_public(real_client):
    assert real_client.get("/health").status_code == 200


# --- demo mode: the active default -----------------------------------------

def test_demo_mode_admits_requests_without_a_token(monkeypatch):
    """With AUTH_MODE=demo the API serves a request that carries no credential."""
    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()

    monkeypatch.setenv("AUTH_MODE", "demo")
    get_settings.cache_clear()

    try:
        with TestClient(app) as demo_client:
            response = demo_client.get("/stations")
        assert response.status_code == 200, response.text
        assert response.json()["count"] == 26
    finally:
        app.dependency_overrides.update(saved_overrides)
        get_settings.cache_clear()
