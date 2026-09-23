"""Graph endpoints: where the generated images are, and the images themselves."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.core.auth import require_user
from app.core.config import get_settings
from app.schemas.solver import GraphFileOut, GraphListOut
from app.services.solver import GRAPH_FILES, graph_path

router = APIRouter(prefix="/graphs", tags=["graphs"])

TITLES = {
    "nn_route": "Classical Nearest Neighbour route map",
    "qaoa_route": "Hybrid QAOA route map",
    "comparison": "Nearest Neighbour vs hybrid QAOA comparison",
}


@router.get(
    "",
    response_model=GraphListOut,
    summary="List the generated graph images",
    description="Paths of the three images the comparison writes, and whether "
                "each has been generated yet. Run POST /solve/compare to "
                "produce or refresh them.",
    dependencies=[Depends(require_user)],
)
def list_graphs() -> GraphListOut:
    settings = get_settings()
    graphs = []
    for name, filename in GRAPH_FILES.items():
        path = settings.outputs_path / filename
        exists = path.is_file()
        modified = (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            if exists else None
        )
        graphs.append(GraphFileOut(
            name=name,
            filename=filename,
            path=str(path),
            url=f"/graphs/{name}",
            exists=exists,
            size_bytes=path.stat().st_size if exists else None,
            modified_at=modified,
        ))
    return GraphListOut(outputs_dir=str(settings.outputs_path), graphs=graphs)


@router.get(
    "/{name}",
    summary="Fetch one graph image",
    description="Serves the PNG. `name` is one of `nn_route`, `qaoa_route` or "
                "`comparison` - no other value resolves, so no path outside "
                "the outputs folder can be reached.",
    response_class=FileResponse,
    responses={
        200: {"content": {"image/png": {}}, "description": "The PNG image."},
        404: {"description": "Unknown graph name, or not generated yet."},
    },
)
def get_graph(name: str) -> FileResponse:
    path = graph_path(name)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "unknown_graph",
                "message": f"No graph named '{name}'.",
                "available": sorted(GRAPH_FILES),
            },
        )
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "graph_not_generated",
                "message": f"'{name}' has not been generated yet.",
                "hint": "POST /solve/compare writes the three images.",
            },
        )
    return FileResponse(path, media_type="image/png",
                        filename=path.name)
