"""Response models for the route energy-loss costing.

Every field is filled from an `energy_cost` result object. The API adds no
numbers of its own, and it never prices a route the analysis could not resolve
to real transmission lines - it reports the gap instead.
"""

from typing import Optional

from pydantic import BaseModel, Field


class TariffOut(BaseModel):
    """The published tariff used, with enough provenance to check it."""

    inr_per_kwh: float = Field(..., description="Energy charge, rupees per kWh.")
    paise_per_kwh: int = Field(..., description="The same rate as the order states it.")
    order_name: str
    authority: str
    order_date: str = Field(..., description="Date the order was issued.")
    effective_period: str
    category: str = Field(..., description="Tariff category the rate belongs to.")
    component: str = Field(
        ..., description="Which billing component this is. Energy charge only."
    )
    source_url: str
    source_location: str = Field(
        ..., description="Where in the order document the rate appears."
    )
    accessed: str = Field(..., description="Date the source was last checked.")
    excludes: list[str] = Field(
        ..., description="Billing components deliberately not included."
    )
    notes: str


class LineUsageOut(BaseModel):
    """One transmission line a route runs over.

    `distance_km`, `loss_percent` and `energy_loss_mw` are dataset values,
    unchanged. The two cost fields are calculated from `energy_loss_mw` and the
    tariff.
    """

    source: str
    destination: str
    distance_km: float
    loss_percent: Optional[float] = None
    energy_loss_mw: Optional[float] = None
    traversals: int = Field(
        ..., description="Times the route crosses this line. Loss is counted once."
    )
    loss_cost_per_hour_inr: Optional[float] = None
    loss_cost_per_year_inr: Optional[float] = None


class UnmatchedStepOut(BaseModel):
    """A route step that resolved to no transmission line."""

    leg_step: int
    origin: str
    destination: str
    reason: str


class RouteEnergyOut(BaseModel):
    """One route's modeled loss and what it is worth."""

    label: str
    start: str
    total_distance_km: float
    line_count: int = Field(
        ..., description="Distinct transmission lines the route uses."
    )
    traversal_count: int
    revisited_lines: int
    total_energy_loss_mw: float = Field(
        ...,
        description="Sum of Energy_Loss_MW over the distinct lines used. "
                    "Dataset values, summed once per line.",
    )
    total_energy_loss_kwh_per_hour: float
    traversal_energy_loss_mw: float = Field(
        ...,
        description="The same sum counted once per traversal, shown for "
                    "transparency. Not the headline figure.",
    )
    loss_cost_per_hour_inr: float = Field(
        ..., description="total_energy_loss_mw x 1000 x tariff."
    )
    loss_cost_per_year_inr: float = Field(
        ..., description="Hourly cost x 8760. An annualised ESTIMATE."
    )
    complete: bool = Field(
        ...,
        description="True when every line used carried an Energy_Loss_MW value "
                    "and every step matched a line.",
    )
    lines_missing_loss: list[LineUsageOut] = Field(
        default_factory=list,
        description="Lines used that carry no Energy_Loss_MW. They contribute "
                    "nothing, so the total is a lower bound.",
    )
    unmatched_steps: list[UnmatchedStepOut] = Field(default_factory=list)
    lines_used: list[LineUsageOut]
    caveats: list[str]


class EnergyTableRowOut(BaseModel):
    label: str
    classical: str
    hybrid: str


class RouteEnergyComparisonOut(BaseModel):
    """Both routes costed at the same tariff, plus the difference.

    Differences are classical minus hybrid, so a positive number means the
    hybrid route is the lower-loss one - the same sign convention the distance
    comparison uses.
    """

    tariff: TariffOut
    classical: RouteEnergyOut
    hybrid: RouteEnergyOut
    distance_difference_km: float
    energy_loss_difference_mw: float
    hourly_cost_difference_inr: float
    annual_cost_difference_inr: float
    lower_loss_route: str = Field(
        ..., description="'hybrid', 'classical' or 'tie', by modeled energy loss."
    )
    hours_per_year: int = Field(
        ..., description="Hours assumed for the annualised estimate."
    )
    annualisation_note: str
    table_rows: list[EnergyTableRowOut]
    framing_note: str
