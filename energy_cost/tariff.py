"""The Karnataka electricity tariff used to price modeled transmission losses.

WHERE THIS NUMBER COMES FROM
----------------------------
It is not an assumption and not a market estimate. It is the energy charge the
Karnataka Electricity Regulatory Commission approved in its Combined Tariff
Order 2025, read from the Commission's own PDF:

    Order      : Combined Tariff Order 2025 of BESCOM / MESCOM / CESC /
                 HESCOM / GESCOM - Annual Performance Review for FY24 and
                 approval of Annual Revenue Requirement and Retail Supply
                 Tariff for the control period FY2025-26 to FY2027-28
    Authority  : Karnataka Electricity Regulatory Commission (KERC)
    Dated      : 27 March 2025
    Located at : Annexure-9, "TARIFF SCHEDULE HT-2(a)", order page 550
    Category   : HT-2(a) - Industries including MSME, factories, industrial
                 workshops and the other installations listed in that schedule
    Component  : Energy Charges (per kWh) - THIS COMPONENT ONLY
    Rate       : 660 paise / kWh = Rs. 6.60 / kWh, for both FY2025-26 and
                 FY2026-27 (the same schedule sets 650 paise for FY2027-28)
    Source     : https://kerc.karnataka.gov.in/uploads/96731743148968.pdf
                 listed on https://kerc.karnataka.gov.in/143/tariff-order-2025/en
    Accessed   : 10 September 2026

WHY HT-2(a)
-----------
The CSV describes a high-voltage transmission network - 66 kV to 400 kV lines
between generating stations and substations. Energy lost on those lines is
energy that was carried at HT level and would otherwise have been delivered to
HT consumers, so the HT industrial energy charge is the closest official
Karnataka rate to the value of that energy. There is no KERC ENERGY charge for
the transmission licensee itself: the KPTCL Tariff Order 2025 sets a
transmission tariff in Rs./kW/month of capacity, which cannot price a kWh.

ENERGY CHARGE ONLY
------------------
Rs. 6.60/kWh is the energy-charge component in isolation. It deliberately
EXCLUDES every other line on a Karnataka electricity bill:

  * demand charges         (HT-2(a): Rs. 345 per kVA per month, FY2025-26)
  * fixed charges
  * FPPCA (fuel and power purchase cost adjustment)
  * the FY2024-25 Annual Performance Review true-up adjustment ordered on
    17 April 2026 (for example +56 paise/unit for BESCOM) - a separate
    recovery component, not the approved energy charge
  * the pension and gratuity surcharge
  * electricity tax and any other statutory levy
  * Time-of-Day adjustments (+/- 100 paise/unit by slot and season)

So a figure produced from this rate is the value of the lost ENERGY, not an
electricity bill.

A NOTE ON Rs. 3.00/kWh
----------------------
A figure of Rs. 3.00/kWh has circulated as "the March 2025 KERC HT industrial
energy charge". It does not survive checking against the order itself: the
FY2025-26 HT-2(a) energy charge in Annexure-9 is 660 paise/kWh. Rs. 3.00/kWh is
not used anywhere in this project.

UPDATING THIS RATE
------------------
When KERC issues a tariff order that supersedes the FY2025-26 to FY2027-28
schedule, change the values below *and* the provenance fields around them, then
re-run `python -m energy_cost.recompute` so the derived CSV columns follow.
Never edit one without the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Hours in a non-leap year. Used only for the annualised ESTIMATE, which
#: assumes the modeled loss is present continuously - see `annualised_cost_inr`.
HOURS_PER_YEAR = 8760

#: 1 MW held for one hour is 1000 kWh.
KWH_PER_MWH = 1000.0


@dataclass(frozen=True)
class TariffRate:
    """One published tariff rate, carried together with its provenance.

    The provenance travels with the number on purpose: every figure this
    project prints in rupees can be traced back to a named order, a category
    and a URL without leaving the code.
    """

    inr_per_kwh: float
    order_name: str
    authority: str
    order_date: str
    effective_period: str
    category: str
    component: str
    source_url: str
    source_location: str
    accessed: str
    excludes: tuple
    notes: str = ""

    @property
    def paise_per_kwh(self) -> int:
        """The rate as the order itself states it, in paise per unit."""
        return round(self.inr_per_kwh * 100)

    @property
    def label(self) -> str:
        return f"{self.category} energy charge, Rs. {self.inr_per_kwh:.2f}/kWh"

    def provenance(self) -> dict:
        """Everything needed to check this rate against the source document."""
        return {
            "inr_per_kwh": self.inr_per_kwh,
            "paise_per_kwh": self.paise_per_kwh,
            "order_name": self.order_name,
            "authority": self.authority,
            "order_date": self.order_date,
            "effective_period": self.effective_period,
            "category": self.category,
            "component": self.component,
            "source_url": self.source_url,
            "source_location": self.source_location,
            "accessed": self.accessed,
            "excludes": list(self.excludes),
            "notes": self.notes,
        }


#: The verified rate this project prices modeled transmission losses at.
KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE = TariffRate(
    inr_per_kwh=6.60,
    order_name=(
        "Combined Tariff Order 2025 of BESCOM / MESCOM / CESC / HESCOM / "
        "GESCOM (Annual Performance Review FY24; ARR and Retail Supply Tariff "
        "for FY2025-26 to FY2027-28)"
    ),
    authority="Karnataka Electricity Regulatory Commission (KERC)",
    order_date="2025-03-27",
    effective_period="FY2025-26 and FY2026-27 (650 paise/kWh from FY2027-28)",
    category="HT-2(a) - Industries including MSME",
    component="Energy Charges (per kWh) only",
    source_url="https://kerc.karnataka.gov.in/uploads/96731743148968.pdf",
    source_location='Annexure-9, "TARIFF SCHEDULE HT-2(a)", order page 550',
    accessed="2026-09-10",
    excludes=(
        "demand charges (Rs. 345/kVA/month, FY2025-26)",
        "fixed charges",
        "FPPCA (fuel and power purchase cost adjustment)",
        "APR FY2024-25 true-up adjustment ordered 17 April 2026",
        "pension and gratuity surcharge",
        "electricity tax and other statutory levies",
        "Time-of-Day adjustments",
    ),
    notes=(
        "Energy charge only. This is the value of the lost energy, not an "
        "electricity bill. The rate is unchanged by the KERC corrigendum of "
        "26 May 2025, which touched the LT-4a subsidy tables and the "
        "Discounted Energy Rate Scheme, not the HT-2(a) schedule."
    ),
)


def resolve_tariff(tariff: Optional[TariffRate] = None) -> TariffRate:
    """The tariff to use: the caller's, or the verified KERC default."""
    return KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE if tariff is None else tariff


def mw_to_kwh_per_hour(loss_mw: float) -> float:
    """Energy in kWh delivered by holding `loss_mw` megawatts for one hour.

    1 MW = 1000 kW, and one hour at 1000 kW is 1000 kWh.
    """
    return loss_mw * KWH_PER_MWH


def hourly_cost_inr(loss_mw: float, tariff: Optional[TariffRate] = None) -> float:
    """Rupee value of one hour of `loss_mw` megawatts of loss.

        Loss_Cost_Per_Hour_INR = Total_Route_Energy_Loss_MW
                                 x 1000
                                 x Tariff_INR_per_kWh
    """
    return mw_to_kwh_per_hour(loss_mw) * resolve_tariff(tariff).inr_per_kwh


def annualised_cost_inr(hourly_inr: float) -> float:
    """Hourly cost scaled to a year. An ESTIMATE, not a yearly bill.

        Loss_Cost_Per_Year_INR = Loss_Cost_Per_Hour_INR x 8760

    This assumes the modeled loss is present for all 8,760 hours of the year.
    The dataset carries no load factor, no generation schedule and no outage
    profile, so nothing here knows how many hours these lines actually run at
    the modeled flow. Read the result as "what a year at this constant loss
    would be worth", never as the real annual loss.
    """
    return hourly_inr * HOURS_PER_YEAR
