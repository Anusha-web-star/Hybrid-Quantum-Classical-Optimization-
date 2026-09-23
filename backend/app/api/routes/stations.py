"""Station endpoints: list them, and resolve a requested starting station."""

from fastapi import APIRouter

from phase1.data_loader import DatasetError
from phase1.network import NetworkError

from app.api import errors
from app.dataio.network import get_network
from app.schemas.network import StartStationOut, StationListOut
from app.schemas.solver import StartRequest
from app.services.serialize import stations_out
from app.services.solver import InvalidStartStation, resolve_start

router = APIRouter(tags=["network"])


@router.get(
    "/stations",
    response_model=StationListOut,
    summary="List every station",
    description="All 26 stations from the CSV, with their type, coordinates "
                "and how many transmission lines meet at each.",
)
def list_stations() -> StationListOut:
    try:
        network = get_network()
    except DatasetError as exc:
        raise errors.dataset_unavailable(exc) from exc

    stations = stations_out(network)
    return StationListOut(count=len(stations), stations=stations)


@router.post(
    "/stations/resolve",
    response_model=StartStationOut,
    summary="Resolve a starting station",
    description="Check a starting station before solving. Matching is "
                "case-insensitive and a unique partial name is accepted. "
                "Returns 422 when the name matches no station or more than one.",
    responses={
        422: {"description": "Unknown or ambiguous starting station."},
        503: {"description": "Dataset unavailable."},
    },
)
def resolve_start_station(request: StartRequest) -> StartStationOut:
    try:
        network = get_network()
    except DatasetError as exc:
        raise errors.dataset_unavailable(exc) from exc
    except NetworkError as exc:
        raise errors.network_unusable(exc) from exc

    try:
        resolved = resolve_start(network, request.start)
    except InvalidStartStation as exc:
        raise errors.invalid_start(exc) from exc

    return StartStationOut(
        requested=request.start,
        resolved=resolved,
        matched_exactly=request.start == resolved,
    )
