"""Authentication for the GRIDOPT API.

Two modes, chosen by `AUTH_MODE` (see `app/core/config.py`).

"demo" - the active one. The browser resolves sign-in against its own local
account store and holds no token, so a request carries no credential and none
is demanded. The sign-in gate is the frontend's alone: it keeps the console
behind a login without a hosted auth service that can rate-limit a signup or
hold an account back for an unconfirmed mailbox. It is not a security boundary,
and it should not be exposed beyond a demo host.

"supabase" - the verification path below, unchanged and still fully tested.
The browser authenticates the user with Supabase Auth and holds the resulting
session. Every request to a protected endpoint carries that session's access
token as `Authorization: Bearer <jwt>`. This module verifies that token the way
any resource server must: it checks the signature against Supabase's published
signing keys and rejects anything unsigned, tampered with, expired, or issued
for a different project or audience.

This project signs tokens with ES256 (asymmetric). Verification therefore needs
only Supabase's PUBLIC keys, fetched once from the JWKS endpoint and cached - no
secret ever lives on this server for this purpose. The service-role key is not
used here and is never required to check a user's token. A shared HS256 secret
is honoured only if one is explicitly configured, for legacy projects.

The frontend "signed in" state is never trusted: a request is authenticated
only if the cryptographic signature on its token verifies here.
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import get_settings

# ES256 is what this project's GoTrue issues; RS256 is accepted too so a project
# configured with RSA keys verifies without a code change.
_ASYMMETRIC_ALGS = ["ES256", "RS256"]

# auto_error=False so a missing/!bearer header becomes our own 401 with a clear
# body, not FastAPI's terse default.
_bearer = HTTPBearer(auto_error=False)


class Unauthorized(HTTPException):
    """A 401 that carries the same structured body shape the rest of the API uses."""

    def __init__(self, message: str):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_authenticated", "message": message},
            headers={"WWW-Authenticate": "Bearer"},
        )


@lru_cache
def _jwks_client() -> PyJWKClient:
    """Cached client over the project's public JWKS. One network fetch, then reused."""
    url = get_settings().supabase_url.rstrip("/")
    return PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json")


def _signing_key(token: str):
    """The public key that signed `token`, from Supabase's JWKS.

    Isolated in its own function so tests can substitute a local public key and
    exercise the real verification path without reaching the network.
    """
    return _jwks_client().get_signing_key_from_jwt(token).key


def verify_token(token: str) -> dict:
    """Return the token's claims if it is a valid Supabase access token, else raise."""
    settings = get_settings()
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise Unauthorized("The access token is malformed.") from exc

    try:
        if header.get("alg") == "HS256":
            if not settings.supabase_jwt_secret:
                raise Unauthorized("Token uses HS256 but no secret is configured.")
            key = settings.supabase_jwt_secret
            algorithms = ["HS256"]
        else:
            key = _signing_key(token)
            algorithms = _ASYMMETRIC_ALGS

        return jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=settings.supabase_jwt_aud,
            issuer=issuer,
            options={"require": ["exp", "sub"]},
        )
    except Unauthorized:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Your session has expired. Sign in again.") from exc
    except jwt.InvalidAudienceError as exc:
        raise Unauthorized("The access token is for a different audience.") from exc
    except jwt.InvalidIssuerError as exc:
        raise Unauthorized("The access token is for a different project.") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("The access token is invalid.") from exc
    except Exception as exc:  # JWKS fetch failure, unknown kid, no crypto backend...
        raise Unauthorized("The access token could not be verified.") from exc


class AuthUser:
    """The authenticated caller, distilled from verified token claims."""

    def __init__(self, claims: dict):
        self.id = claims.get("sub")
        self.email = claims.get("email")
        self.claims = claims


# The caller every request is attributed to while AUTH_MODE=demo. Nothing is
# verified here; the frontend decides who may reach the API at all.
DEMO_USER_CLAIMS = {
    "sub": "demo-user",
    "email": "demo@gridopt.local",
    "aud": "authenticated",
}


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """FastAPI dependency: 401 unless the request carries a valid Bearer token.

    In demo mode there is no token to check, so every request is admitted as the
    demo user and the verification below never runs.
    """
    if get_settings().auth_mode != "supabase":
        return AuthUser(DEMO_USER_CLAIMS)
    if credentials is None or not credentials.credentials:
        raise Unauthorized("Sign in to use this endpoint.")
    if credentials.scheme.lower() != "bearer":
        raise Unauthorized("Use a Bearer token.")
    return AuthUser(verify_token(credentials.credentials))
