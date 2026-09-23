"""Cached access to the Phase 1 dataset and network.

The CSV is the single source of truth and `phase1.data_loader` already knows how
to read and validate it, so nothing here parses the file or builds the graph
itself - it only loads them once and hands the same objects to every request.
"""

from functools import lru_cache

from phase1.data_loader import Dataset, DatasetError, load_dataset
from phase1.network import Network

from app.core.config import get_settings


@lru_cache
def get_dataset() -> Dataset:
    """The parsed CSV, loaded once per process.

    Raises `DatasetError` when the file is missing or unusable; the API turns
    that into a 503, since without the dataset it can answer nothing.
    """
    settings = get_settings()
    return load_dataset(data_dir=str(settings.data_path))


@lru_cache
def get_network() -> Network:
    """The station graph, built once and reused.

    `Network` fills its shortest-path closure lazily, so caching the instance
    also spares every request after the first from re-running Dijkstra.
    """
    return Network(get_dataset())


def dataset_info() -> dict:
    """What was loaded, for the status endpoint. Never raises."""
    settings = get_settings()
    try:
        dataset = get_dataset()
    except DatasetError as exc:
        return {
            "found": False,
            "path": None,
            "searched_in": str(settings.data_path),
            "message": str(exc),
        }
    return {
        "found": True,
        "path": str(dataset.path),
        "searched_in": str(settings.data_path),
        "message": "Dataset loaded.",
        "stations": len(dataset.stations),
        "rows": len(dataset.connections),
        "routable_lines": len(dataset.routable_connections),
        "warnings": list(dataset.warnings),
    }
