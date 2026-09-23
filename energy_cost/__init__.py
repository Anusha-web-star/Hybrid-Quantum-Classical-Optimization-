"""Route-level energy-loss costing.

This package is *analysis only*. It reads the `Energy_Loss_MW` values the
transmission-line CSV already carries, maps a solved route onto the physical
lines it uses, and prices the resulting loss at a verified Karnataka tariff.

It changes no optimization. `phase1.nn_tsp` and `phase2.hybrid` still minimize
the same `Distance_km` TSP objective they always have; this package looks at the
tour they produced and says what the modeled losses on it are worth.

    tariff      the verified KERC energy charge and its provenance
    route_loss  route -> transmission lines -> modeled loss -> money
"""

from .route_loss import (LineUsage, RouteEnergyComparison, RouteEnergyLoss,
                         compare_routes, route_energy_loss)
from .tariff import (HOURS_PER_YEAR, KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE,
                     TariffRate, annualised_cost_inr, hourly_cost_inr,
                     mw_to_kwh_per_hour)

__all__ = [
    "HOURS_PER_YEAR",
    "KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE",
    "LineUsage",
    "RouteEnergyComparison",
    "RouteEnergyLoss",
    "TariffRate",
    "annualised_cost_inr",
    "compare_routes",
    "hourly_cost_inr",
    "mw_to_kwh_per_hour",
    "route_energy_loss",
]
