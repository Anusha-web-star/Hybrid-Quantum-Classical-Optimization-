"""The network endpoint: the whole graph as the CSV defines it."""

from fastapi import APIRouter

from phase1.data_loader import DatasetError

from app.api import errors
from app.dataio.network import get_dataset, get_network
from app.schemas.network import NetworkOut
from app.services.serialize import lines_out, stations_out, summary_out

router = APIRouter(tags=["network"])


@router.get(
    "/network",
    response_model=NetworkOut,
    summary="Get the network and transmission-line data",
    description="The 26 stations and all 38 routable transmission lines, with "
                "the distance, voltage, capacity and loss figures carried "
                "straight from the CSV. Nothing is derived or modified.",
    responses={503: {"description": "Dataset unavailable."}},
)
def get_network_data() -> NetworkOut:
    try:
        dataset = get_dataset()
        network = get_network()
    except DatasetError as exc:
        raise errors.dataset_unavailable(exc) from exc

    return NetworkOut(
        dataset_path=str(dataset.path),
        summary=summary_out(network),
        stations=stations_out(network),
        transmission_lines=lines_out(network),
    )
