"""Request and response models for the solver endpoints.

Every field here is filled from a Phase 1 or Phase 2 result object. The API adds
no numbers of its own.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.energy import RouteEnergyComparisonOut


class StartRequest(BaseModel):
    """Just a starting station - all the classical solver needs."""

    start: str = Field(
        ...,
        min_length=1,
        description="Starting station. Matched case-insensitively, and a "
                    "unique partial name is accepted.",
        examples=["Mysuru Substation"],
    )


class HybridOptions(BaseModel):
    """Optional overrides for the hybrid run.

    Defaults come from settings and mirror `run_phase2.py`. There is no
    execution-mode field on purpose: the API always uses the local simulator
    and never submits an IBM Quantum job.
    """

    window: Optional[int] = Field(
        None, ge=3, le=5,
        description="Stations reordered per QAOA subproblem (W^2 qubits).",
    )
    sweeps: Optional[int] = Field(
        None, ge=1, le=20, description="Cap on reoptimization sweeps."
    )
    reps: Optional[int] = Field(None, ge=1, le=6, description="QAOA depth p.")
    shots: Optional[int] = Field(None, ge=128, le=32768)
    maxiter: Optional[int] = Field(None, ge=5, le=500,
                                   description="COBYLA iterations per restart.")
    restarts: Optional[int] = Field(None, ge=1, le=10)
    cvar: Optional[float] = Field(None, gt=0.0, le=1.0,
                                  description="CVaR tail fraction.")
    seed: Optional[int] = Field(None, description="Sampler / angle seed.")
    prune: bool = Field(True, description="Skip windows that cannot improve.")


class HybridRequest(StartRequest, HybridOptions):
    """A starting station plus the optional hybrid knobs."""


class CompareRequest(HybridRequest):
    render_graphs: bool = Field(
        True,
        description="Write the two route maps and the comparison figure.",
    )


class LegOut(BaseModel):
    step: int
    origin: str
    destination: str
    distance_km: float
    is_direct: bool = Field(
        ..., description="True when one transmission line joins the two stations."
    )
    via: list[str] = Field(
        ..., description="Stations passed through without being visited yet."
    )


class CheckOut(BaseModel):
    label: str
    passed: bool


class TourOut(BaseModel):
    """One solved tour, from a Phase 1 `TourResult`."""

    start: str
    order: list[str] = Field(..., description="Visiting order, start listed once.")
    closed_route: list[str] = Field(
        ..., description="The full route with the start repeated at the end."
    )
    total_distance_km: float
    execution_time_s: float
    stations_visited: int
    direct_legs: int
    legs: list[LegOut]
    valid: bool
    checks: list[CheckOut]


class ClassicalSolveOut(BaseModel):
    algorithm: str = "classical-nearest-neighbour"
    start: str
    tour: TourOut


class HybridDetailOut(BaseModel):
    """How the hybrid search got to its tour."""

    mode: str
    backend: str
    window: int
    qubits_per_subproblem: int
    sweeps_run: int
    subproblems_solved: int
    subproblems_skipped: int
    improvements_accepted: int
    qaoa_evaluations: int
    start_distance_km: float = Field(
        ..., description="The classical tour the reoptimization started from."
    )


class HybridSolveOut(BaseModel):
    algorithm: str = "hybrid-qaoa-reoptimization"
    start: str
    tour: TourOut
    detail: HybridDetailOut


class TableRowOut(BaseModel):
    label: str
    classical: str
    hybrid: str


class ComparisonOut(BaseModel):
    """The Phase 2 comparison, straight from `phase2.comparison.Comparison`."""

    start: str
    stations: int
    lines: int
    dataset_path: str
    nn_distance_km: float
    nn_time_s: float
    nn_valid: bool
    hybrid_distance_km: float
    hybrid_time_s: float
    hybrid_valid: bool
    improvement_km: float = Field(
        ..., description="Displayed NN distance minus displayed hybrid distance."
    )
    improvement_percent: float = Field(
        ..., description="improvement_km as a percentage of the NN distance."
    )
    winner: str = Field(..., description="'hybrid', 'classical' or 'tie'.")
    table_rows: list[TableRowOut]
    framing_note: str
    same_problem_checks: list[CheckOut]


class GraphsOut(BaseModel):
    """Where the generated images live."""

    outputs_dir: str
    nn_route: Optional[str] = None
    qaoa_route: Optional[str] = None
    comparison: Optional[str] = None
    urls: dict[str, str] = Field(
        default_factory=dict,
        description="Endpoint paths that serve each image.",
    )


class CompareOut(BaseModel):
    start: str
    classical: ClassicalSolveOut
    hybrid: HybridSolveOut
    comparison: ComparisonOut
    energy: RouteEnergyComparisonOut = Field(
        ...,
        description="Modeled transmission loss on each route and what it is "
                    "worth. An analysis of the chosen tours; neither solver "
                    "optimizes for energy loss.",
    )
    graphs: GraphsOut


class GraphFileOut(BaseModel):
    name: str
    filename: str
    path: str
    url: str
    exists: bool
    size_bytes: Optional[int] = None
    modified_at: Optional[str] = None


class GraphListOut(BaseModel):
    outputs_dir: str
    graphs: list[GraphFileOut]
