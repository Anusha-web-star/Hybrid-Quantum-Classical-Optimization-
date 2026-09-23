"""Health and dataset-presence endpoints."""

from fastapi import APIRouter

from app.core.config import Settings, get_settings
from app.dataio.network import dataset_info

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness check")
def health() -> dict:
    settings: Settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "phase": "3 - FastAPI backend",
    }


@router.get("/dataset/status", summary="Report the loaded dataset")
def dataset_status() -> dict:
    """Whether the transmission-line CSV loaded, and what it contains.

    `expected_path` is the conventional filename; `path` is the CSV Phase 1
    actually discovered and read, which is the one every endpoint uses.
    """
    settings: Settings = get_settings()
    info = dataset_info()
    return {
        "expected_path": str(settings.transmission_lines_path),
        **info,
    }
