"""Shared HTTP error translation for the API.

Phase 1 and Phase 2 raise their own exceptions. Routes map them here so a bad
request gets a clear, machine-readable reason instead of a 500.
"""

from fastapi import HTTPException, status

from phase1.data_loader import DatasetError
from phase1.network import NetworkError

from app.dataio.network import get_network
from app.services.solver import InvalidStartStation

# 422: the request was well formed, but the station named in it cannot be used.
# Spelled as the literal code - Starlette has renamed this constant across versions.
INVALID_START_STATUS = 422


def invalid_start(exc: InvalidStartStation) -> HTTPException:
    """Turn an unresolvable starting station into a helpful 422."""
    try:
        station_count = len(get_network().names)
    except (DatasetError, NetworkError):
        station_count = None

    return HTTPException(
        status_code=INVALID_START_STATUS,
        detail={
            "error": exc.code,
            "message": exc.message,
            "suggestions": exc.suggestions,
            "station_count": station_count,
            "hint": "GET /stations lists every valid starting station.",
        },
    )


def dataset_unavailable(exc: Exception) -> HTTPException:
    """The CSV is missing or unusable - the API cannot answer anything."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "dataset_unavailable", "message": str(exc)},
    )


def network_unusable(exc: NetworkError) -> HTTPException:
    """The graph loaded, but the requested tour cannot exist on it."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": "network_unusable", "message": str(exc)},
    )
