"""Map a solved route onto the transmission lines it uses, and price the loss.

    route -> transmission lines used -> modeled energy loss -> estimated money

HOW A ROUTE MAPS ONTO PHYSICAL LINES
------------------------------------
This is the part that needs saying out loud, because a route leg is NOT a
transmission line.

The network is sparse: 26 stations joined by 38 lines, so most station pairs
have no line between them. `phase1.network.Network` therefore routes over the
shortest-path closure, and a single leg of the tour - "Mysuru Substation to
Kaiga" - can be a chain of several real lines with pass-through stations in
between. Every `Leg` records that chain in `leg.path`.

So the mapping walks `leg.path` pair by pair. Each consecutive pair in a path
IS a real transmission line, because `Network.travel_path` only ever steps along
`Network.adjacency`. Each such step is looked up with `Network.edge_between`,
which returns the `Edge` carrying the CSV's own `Distance_km`, `Loss_Percent`
and `Energy_Loss_MW`. No value is recomputed and none is invented.

WHY DISTINCT LINES, NOT TRAVERSALS
----------------------------------
On a sparse network a tour often crosses the same line more than once. That
matters for how the loss is summed.

`Energy_Loss_MW` is a steady-state property of a line: the power that line
dissipates while it carries its modeled flow. It is not a per-trip quantity, so
adding it once per traversal would count the same continuously-present loss
twice.

The headline figure is therefore the sum over DISTINCT lines used by the route:

    Total_Route_Energy_Loss_MW = sum of Energy_Loss_MW over the set of
                                 transmission lines the route touches

The traversal-weighted sum is reported alongside it as
`traversal_energy_loss_mw`, so the difference is visible rather than hidden.

WHAT IS NOT CLAIMED
-------------------
Distance does not determine loss here. The route's total km and the route's
total loss are two independent readings taken from the same set of lines: a
short route over lossy lines can lose more than a long route over efficient
ones. Nothing in this module derives loss from length.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .tariff import (TariffRate, annualised_cost_inr, hourly_cost_inr,
                     resolve_tariff)


@dataclass
class LineUsage:
    """One physical transmission line used by a route.

    `distance_km`, `loss_percent` and `energy_loss_mw` are the dataset's own
    values, passed through untouched. The two cost fields are DERIVED.
    """

    source: str
    destination: str
    distance_km: float
    loss_percent: Optional[float]
    energy_loss_mw: Optional[float]
    traversals: int
    loss_cost_per_hour_inr: Optional[float]
    loss_cost_per_year_inr: Optional[float]

    @property
    def key(self) -> tuple:
        return (self.source, self.destination)


@dataclass
class UnmatchedStep:
    """A step of a route that could not be resolved to a transmission line.

    In a well-formed run this list stays empty: every step of a `travel_path`
    follows an adjacency entry, and every adjacency entry has an `Edge`. It
    exists so that a malformed route is reported rather than silently costed as
    if it were free.
    """

    leg_step: int
    origin: str
    destination: str
    reason: str


@dataclass
class RouteEnergyLoss:
    """What one solved route costs in modeled transmission loss.

    SOURCE values      : `distance_km`, `loss_percent`, `energy_loss_mw` on each
                         line, straight from the CSV.
    DERIVED values     : every `*_cost_*` field, the totals, and the counts.
    """

    label: str
    start: str
    total_distance_km: float
    lines_used: list                      # list[LineUsage], distinct lines
    total_energy_loss_mw: float           # distinct-line sum, the headline
    traversal_energy_loss_mw: float       # counted once per traversal
    traversal_count: int
    lines_missing_loss: list              # list[LineUsage] with no Energy_Loss_MW
    unmatched_steps: list                 # list[UnmatchedStep]
    tariff: TariffRate
    loss_cost_per_hour_inr: float
    loss_cost_per_year_inr: float

    @property
    def line_count(self) -> int:
        """Distinct transmission lines the route runs over."""
        return len(self.lines_used)

    @property
    def revisited_lines(self) -> int:
        """Lines the route crosses more than once."""
        return sum(1 for line in self.lines_used if line.traversals > 1)

    @property
    def is_complete(self) -> bool:
        """True when every line used carried an `Energy_Loss_MW` value."""
        return not self.lines_missing_loss and not self.unmatched_steps

    @property
    def total_energy_loss_kwh_per_hour(self) -> float:
        """The headline loss expressed as energy over one hour."""
        return self.total_energy_loss_mw * 1000.0

    def caveats(self) -> list:
        """Plain-language notes a reader needs to interpret these numbers."""
        notes = [
            "Annualised cost is an ESTIMATE: it assumes the modeled loss is "
            "present for all 8,760 hours of the year. The dataset carries no "
            "load factor or operating profile, so this is not an actual "
            "yearly loss and not an electricity bill.",
            f"Priced at the {self.tariff.category} energy charge only "
            f"(Rs. {self.tariff.inr_per_kwh:.2f}/kWh). Fixed charges, demand "
            f"charges, FPPCA, taxes and other billing components are excluded.",
            "Energy loss is summed once per distinct transmission line used. "
            "Energy_Loss_MW is a steady-state property of a line, so a line "
            "crossed twice is still counted once.",
            "Route distance and route loss are separate readings from the "
            "same lines. Distance does not determine loss.",
        ]
        if self.lines_missing_loss:
            names = ", ".join(
                f"{line.source} - {line.destination}"
                for line in self.lines_missing_loss
            )
            notes.append(
                f"{len(self.lines_missing_loss)} line(s) used by this route "
                f"carry no Energy_Loss_MW in the dataset and contribute "
                f"nothing to the total: {names}. The figure is a lower bound."
            )
        if self.unmatched_steps:
            notes.append(
                f"{len(self.unmatched_steps)} route step(s) could not be "
                f"matched to a transmission line and were excluded."
            )
        return notes


@dataclass
class RouteEnergyComparison:
    """Two costed routes side by side, plus the difference between them."""

    classical: RouteEnergyLoss
    hybrid: RouteEnergyLoss
    tariff: TariffRate = field(default=None)

    def __post_init__(self):
        if self.tariff is None:
            self.tariff = self.classical.tariff

    # Differences are always classical minus hybrid, so a POSITIVE number means
    # the hybrid route is the cheaper / lower-loss one - matching the sign
    # convention `phase2.comparison.Comparison.improvement_km` already uses.

    @property
    def distance_difference_km(self) -> float:
        return self.classical.total_distance_km - self.hybrid.total_distance_km

    @property
    def energy_loss_difference_mw(self) -> float:
        return self.classical.total_energy_loss_mw - self.hybrid.total_energy_loss_mw

    @property
    def hourly_cost_difference_inr(self) -> float:
        return (self.classical.loss_cost_per_hour_inr
                - self.hybrid.loss_cost_per_hour_inr)

    @property
    def annual_cost_difference_inr(self) -> float:
        return (self.classical.loss_cost_per_year_inr
                - self.hybrid.loss_cost_per_year_inr)

    @property
    def lower_loss_route(self) -> str:
        """'hybrid', 'classical' or 'tie' by modeled energy loss."""
        if abs(self.energy_loss_difference_mw) < 1e-9:
            return "tie"
        return "hybrid" if self.energy_loss_difference_mw > 0 else "classical"

    def table_rows(self) -> list:
        """(label, classical, hybrid) triples, mirroring the Phase 2 table."""
        return [
            ("Total route distance",
             f"{self.classical.total_distance_km:,.3f} km",
             f"{self.hybrid.total_distance_km:,.3f} km"),
            ("Transmission lines used",
             f"{self.classical.line_count}",
             f"{self.hybrid.line_count}"),
            ("Modeled energy loss",
             f"{self.classical.total_energy_loss_mw:,.3f} MW",
             f"{self.hybrid.total_energy_loss_mw:,.3f} MW"),
            ("Estimated loss cost / hour",
             f"Rs. {self.classical.loss_cost_per_hour_inr:,.2f}",
             f"Rs. {self.hybrid.loss_cost_per_hour_inr:,.2f}"),
            ("Annualised loss cost (estimate)",
             f"Rs. {self.classical.loss_cost_per_year_inr:,.2f}",
             f"Rs. {self.hybrid.loss_cost_per_year_inr:,.2f}"),
        ]

    def framing_note(self) -> str:
        return (
            "Analysis of the routes the solvers already chose. Both still "
            "minimize the same Distance_km TSP objective - energy loss is not "
            "part of either cost function. Estimated using the verified "
            "Karnataka HT energy-charge tariff; this excludes fixed charges, "
            "FPPCA, taxes and other billing components."
        )


def _walk_line_steps(result):
    """Yield (leg_step, a, b) for every physical line step the route takes.

    A leg's `path` is the chain of stations actually traversed, so consecutive
    entries in it are real transmission lines. A direct leg yields one step; a
    leg routed through pass-through stations yields one per hop.
    """
    for leg in result.legs:
        path = list(getattr(leg, "path", None) or [])
        if len(path) < 2:
            # A leg with no recorded path cannot be resolved to lines. Report
            # it instead of guessing a straight-line equivalent.
            yield leg.step, leg.origin, leg.destination, False
            continue
        for a, b in zip(path, path[1:]):
            yield leg.step, a, b, True


def route_energy_loss(
    network,
    result,
    label: str = "route",
    tariff: Optional[TariffRate] = None,
) -> RouteEnergyLoss:
    """Cost the modeled transmission loss on one solved tour.

    `result` is a `phase1.nn_tsp.TourResult` - which is also what
    `phase2.hybrid.HybridResult.tour` holds, so the classical and the hybrid
    route are costed by the same code path on the same network.

    Nothing about the tour is changed and no optimization is performed.
    """
    rate = resolve_tariff(tariff)

    usage: dict = {}          # (a, b) -> [Edge, traversals]
    unmatched: list = []

    for step, a, b, has_path in _walk_line_steps(result):
        if not has_path:
            unmatched.append(UnmatchedStep(
                step, a, b,
                "the leg records no traversed path, so it maps to no line",
            ))
            continue

        edge = network.edge_between(a, b)
        if edge is None:
            unmatched.append(UnmatchedStep(
                step, a, b,
                "no transmission line in the dataset joins these two stations",
            ))
            continue

        key = (edge.a, edge.b)
        if key in usage:
            usage[key][1] += 1
        else:
            usage[key] = [edge, 1]

    lines: list = []
    missing: list = []
    total_loss = 0.0
    traversal_loss = 0.0
    traversals = 0

    for key in sorted(usage):
        edge, count = usage[key]
        traversals += count

        loss = edge.energy_loss_mw
        if loss is None:
            hourly = yearly = None
        else:
            total_loss += loss
            traversal_loss += loss * count
            hourly = hourly_cost_inr(loss, rate)
            yearly = annualised_cost_inr(hourly)

        line = LineUsage(
            source=edge.a,
            destination=edge.b,
            distance_km=edge.distance_km,
            loss_percent=edge.loss_percent,
            energy_loss_mw=loss,
            traversals=count,
            loss_cost_per_hour_inr=hourly,
            loss_cost_per_year_inr=yearly,
        )
        lines.append(line)
        if loss is None:
            missing.append(line)

    route_hourly = hourly_cost_inr(total_loss, rate)

    return RouteEnergyLoss(
        label=label,
        start=result.start,
        total_distance_km=result.total_distance_km,
        lines_used=lines,
        total_energy_loss_mw=total_loss,
        traversal_energy_loss_mw=traversal_loss,
        traversal_count=traversals,
        lines_missing_loss=missing,
        unmatched_steps=unmatched,
        tariff=rate,
        loss_cost_per_hour_inr=route_hourly,
        loss_cost_per_year_inr=annualised_cost_inr(route_hourly),
    )


def compare_routes(
    network,
    nn_result,
    hybrid_result,
    tariff: Optional[TariffRate] = None,
) -> RouteEnergyComparison:
    """Cost both solvers' routes on the same network at the same tariff.

    `hybrid_result` may be a `phase2.hybrid.HybridResult` or the `TourResult`
    inside it; both are accepted so callers do not have to unwrap it.
    """
    rate = resolve_tariff(tariff)
    hybrid_tour = getattr(hybrid_result, "tour", hybrid_result)

    return RouteEnergyComparison(
        classical=route_energy_loss(network, nn_result, "Classical NN", rate),
        hybrid=route_energy_loss(network, hybrid_tour, "Hybrid QAOA", rate),
        tariff=rate,
    )
