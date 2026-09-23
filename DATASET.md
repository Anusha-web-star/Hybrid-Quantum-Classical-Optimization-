# DATASET

The transmission-line CSV in `data/` is the single dataset file for this
project. There is one CSV and there will only ever be one: nothing here
generates a network, substitutes a missing value, or writes a second file.

    data/transmition_lines.csv.csv     26 stations, 38 transmission lines

Phase 1 auto-detects the single `*.csv` in `data/`; pass `--data PATH` to point
somewhere else.

---

## 1. Source data vs. derived data

This distinction runs through the whole document. Nothing below blurs it.

| | Meaning |
|---|---|
| **SOURCE** | Values that arrived with the dataset. Read, never recomputed, never overwritten. |
| **DERIVED** | Values this project calculates from source values plus a published tariff. Every one of them is reproducible from the formulas in section 5. |

### SOURCE columns

| Column | Type | Role |
|--------|------|------|
| `Source`, `Destination` | text | The two stations a line joins. These are the graph's nodes and edges. |
| `Type` | text | Facility type of the **source** station (thermal, substation, hydro, …). Used as the map label. It is not copied to the destination; a station picks up its own type from its own rows. |
| `Source_Latitude`, `Source_Longitude` | float | Map position of the source station. |
| `Destination_Latitude`, `Destination_Longitude` | float | Map position of the destination station. |
| `Distance_km` | float | Length of the line. **This is the TSP route cost** and the only quantity either solver minimizes. |
| `Voltage_kV` | float | Line voltage, 66–400 kV. |
| `Capacity_MW` | float | Line capacity. |
| `Loss_Percent` | float | Modeled loss on the line, as a percentage. |
| `Energy_Loss_MW` | float | Modeled power lost on the line. See section 3. |

### DERIVED columns

These two were **added** to the existing CSV. They sit after every source
column, and no source value was altered to make room for them — each row is its
original text with two fields appended.

| Column | Type | Definition |
|--------|------|------------|
| `Loss_Cost_Per_Hour_INR` | float | `Energy_Loss_MW × 1000 × Tariff_INR_per_kWh` — calculated |
| `Loss_Cost_Per_Year_INR` | float | `Loss_Cost_Per_Hour_INR × 8760` — calculated, **annualised estimate** |

A row whose `Energy_Loss_MW` is blank gets two blank cells. It never gets a
substituted number.

Both columns are owned by `energy_cost/recompute.py`:

```
python -m energy_cost.recompute          # rewrite them at the current tariff
python -m energy_cost.recompute --check  # report drift without writing
```

`tests/test_energy_cost.py` runs the `--check` path, so a tariff change that is
not followed through to the CSV fails the suite instead of drifting silently.

---

## 2. `Energy_Loss_MW` — definition and standing

`Energy_Loss_MW` is the **modeled steady-state power dissipated by one
transmission line**, in megawatts, while that line carries its modeled flow.

Three consequences follow, and all three shape how it is used:

1. **It is a power figure, not an energy figure.** It becomes energy only when
   multiplied by a duration. One hour at *N* MW is *N* × 1000 kWh.
2. **It is a property of the line, not of a trip across it.** A line dissipates
   this power continuously while energised. Crossing it twice does not double
   it — see section 4.
3. **It is modeled, not metered.** The dataset supplies no measurement
   provenance, no load factor, no time series and no operating schedule. Every
   figure built on it inherits that standing.

`Loss_Percent` is carried alongside it and shown in the UI, but the route
totals are built from `Energy_Loss_MW`, which is already an absolute quantity.

> **Loss is not a function of distance here.** A long line over efficient
> conductors can lose less than a short heavily loaded one. Route distance and
> route loss are two independent readings taken from the same set of lines.
> Nothing in this project derives one from the other.

---

## 3. How a route maps onto transmission lines

This is the part that needs stating plainly, because **a route leg is not a
transmission line**.

The network is sparse: 26 stations joined by 38 lines, so most station pairs
have no direct line between them. `phase1.network.Network` therefore routes over
the **shortest-path closure** — `travel_cost(a, b)` is the length of the
shortest chain of real lines from `a` to `b`, found by Dijkstra over
`Distance_km`. A single leg of the tour can therefore be a chain of several real
lines, with pass-through stations in between.

Every `Leg` records that chain in `leg.path`, the stations physically traversed
including both ends. The mapping walks it:

```
for each leg in the route:
    for each consecutive pair (a, b) in leg.path:
        line = network.edge_between(a, b)     # a real CSV row
        record line, and count one traversal
```

Each consecutive pair in a `path` **is** a real line, because `travel_path` only
ever steps along the adjacency built from the CSV. Every line the analysis
reports is a row of the dataset, carrying that row's own `Distance_km`,
`Loss_Percent` and `Energy_Loss_MW`.

### Unmatched steps

Two cases are reported rather than guessed at:

| Case | Handling |
|------|----------|
| A step whose two stations have no line between them | Recorded in `unmatched_steps` with a reason; contributes nothing to the total. |
| A leg that records no traversed path at all | Recorded in `unmatched_steps`; contributes nothing. |
| A line used whose `Energy_Loss_MW` is blank | Recorded in `lines_missing_loss`; contributes nothing, and the route total is flagged as a **lower bound**. |

On the current dataset all three lists are empty: every leg of both routes
resolves to lines that carry a loss value. The handling exists so that a future
dataset with gaps is reported honestly rather than costed as if the gaps were
zero.

---

## 4. Route-level energy loss

    Total_Route_Energy_Loss_MW = sum of Energy_Loss_MW
                                 over the DISTINCT transmission lines
                                 the route runs over

**Distinct lines, counted once each.** Because `Energy_Loss_MW` is a
steady-state property of a line (section 2), adding it once per traversal would
count the same continuously-present loss twice. A tour on a sparse network
regularly recrosses lines, so this is not a corner case.

The traversal-weighted sum is reported alongside it as
`traversal_energy_loss_mw`, together with `traversal_count` and
`revisited_lines`, so the difference between the two conventions is visible
rather than buried.

For the reference run — Nearest Neighbour from Mysuru Substation — the tour's
26 legs expand into 45 traversals over 31 distinct lines, 13 of which are
crossed more than once.

---

## 5. The tariff, and the money

### The rate

| Field | Value |
|---|---|
| **Order** | Combined Tariff Order 2025 of BESCOM / MESCOM / CESC / HESCOM / GESCOM — Annual Performance Review for FY24 and approval of ARR and Retail Supply Tariff for the control period FY2025-26 to FY2027-28 |
| **Authority** | Karnataka Electricity Regulatory Commission (KERC) |
| **Order date** | 27 March 2025 |
| **Located at** | Annexure-9, "TARIFF SCHEDULE HT-2(a)", order page 550 |
| **Category** | HT-2(a) — Industries including MSME |
| **Component** | Energy Charges (per kWh) — **this component only** |
| **Rate** | **660 paise/kWh = ₹6.60/kWh** |
| **Applicable years** | FY2025-26 and FY2026-27 (the same schedule sets 650 paise/kWh for FY2027-28) |
| **Source** | <https://kerc.karnataka.gov.in/uploads/96731743148968.pdf>, listed on <https://kerc.karnataka.gov.in/143/tariff-order-2025/en> |
| **Date accessed** | 10 September 2026 |

Verified by extracting the text of the Commission's own PDF, not from a news
report or a secondary summary. The KERC corrigendum of 26 May 2025 was also
checked: it amends the LT-4a subsidy tables and the Discounted Energy Rate
Scheme, and leaves the HT-2(a) schedule untouched.

### Why this category

The CSV describes a high-voltage transmission network — 66 kV to 400 kV lines
between generating stations and substations. Energy lost on those lines is
energy carried at HT level that would otherwise have reached HT consumers, so
the HT industrial energy charge is the closest official Karnataka rate to what
that energy is worth.

KERC's **KPTCL Tariff Order 2025** was considered and rejected for this purpose:
the transmission tariff it sets is in ₹/kW/month of capacity, which cannot price
a kWh.

### On the ₹3.00/kWh figure

A figure of ₹3.00/kWh has circulated as "the March 2025 KERC HT industrial
energy charge". **It does not survive checking against the order.** The
FY2025-26 HT-2(a) energy charge in Annexure-9 is 660 paise/kWh. ₹3.00/kWh is
used nowhere in this project.

### ENERGY CHARGE ONLY — what is excluded

₹6.60/kWh is the energy-charge component in isolation. Every other line on a
Karnataka electricity bill is deliberately **excluded**:

- demand charges (HT-2(a): ₹345 per kVA per month, FY2025-26)
- fixed charges
- FPPCA (fuel and power purchase cost adjustment)
- the FY2024-25 Annual Performance Review true-up adjustment ordered
  17 April 2026 (for example +56 paise/unit for BESCOM) — a separate recovery
  component, not the approved energy charge
- the pension and gratuity surcharge
- electricity tax and other statutory levies
- Time-of-Day adjustments (±100 paise/unit by slot and season)

**A figure produced from this rate is the value of the lost energy. It is not an
electricity bill.**

### The formulas

    Loss_Cost_Per_Hour_INR = Total_Route_Energy_Loss_MW
                             × 1000                       (1 MW = 1000 kW,
                                                           1 MW for 1 h = 1000 kWh)
                             × Tariff_INR_per_kWh         (= 6.60)

    Loss_Cost_Per_Year_INR = Loss_Cost_Per_Hour_INR × 8760

Both are applied identically at line level (the two derived CSV columns) and at
route level (the API's `energy` block), so a route total is the sum of its
lines' hourly costs.

### The 8,760-hour assumption

`Loss_Cost_Per_Year_INR` is an **ANNUALISED ESTIMATE**, and the label matters.

Multiplying by 8,760 assumes the modeled loss is present **continuously, for
every hour of the year**. The dataset carries no load factor, no generation
schedule, no dispatch profile and no outage data, so nothing in this project
knows how many hours these lines actually run at the modeled flow. Renewable
sources in the network — Pavagada Solar Park, the wind clusters — plainly do not
run flat out for 8,760 hours a year.

Read the annual figure as *"what a year at this constant loss would be worth"*.
It is **not**:

- an actual yearly loss
- an actual electricity bill
- a forecast

It would become a real annual figure only if the dataset gained a real load
factor or operating profile. It has neither.

---

## 6. Limitations

1. **Modeled, not metered.** `Energy_Loss_MW` and `Loss_Percent` arrive with no
   measurement provenance. Everything downstream is only as good as they are.
2. **No time dimension.** One steady-state number per line, no load curve, no
   seasonality. This is what forces the 8,760-hour assumption.
3. **Snapshot tariff.** ₹6.60/kWh is the FY2025-26/FY2026-27 approved energy
   charge. It will be superseded. When it is, update
   `energy_cost/tariff.py` — the rate and its provenance fields together — and
   re-run `python -m energy_cost.recompute`.
4. **One tariff for the whole network.** The 26 stations span several ESCOM
   territories (BESCOM, HESCOM, GESCOM, CESC, MESCOM). The single combined
   order sets the same HT-2(a) schedule for all of them, so one rate is correct
   here — but a future order that differentiates by ESCOM would need this
   revisited.
5. **Retail rate on bulk energy.** The HT industrial energy charge is what an HT
   consumer pays, which is not identical to the utility's cost of procuring the
   lost energy (KERC records BESCOM's average power purchase cost at
   ₹6.44/unit for FY24 and ₹6.54/unit for FY25). The HT-2(a) charge is used
   because it is a Commission-*approved tariff*; the power purchase cost is a
   licensee's reported cost, not a tariff.
6. **Loss is analysed, never optimized.** Both solvers minimize `Distance_km`
   and nothing else. See section 7.
7. **Parallel lines.** Where the CSV lists two lines between the same pair of
   stations, `Network` routes over the shorter one, and only that one is costed.
   The current dataset has no such pair — 38 rows produce 38 routable lines.

---

## 7. This is analysis, not an optimization objective

The route energy-loss costing looks at the tours the solvers **already chose**.
It changes no algorithm:

- `phase1.nn_tsp.solve` still minimizes `Distance_km`.
- `phase2.hybrid.hybrid_solve` still minimizes `Distance_km`.
- The QAOA configuration is untouched.

Energy loss is not a term in either cost function. A consequence worth naming:
**the shorter route is not automatically the lower-loss route.** On the
reference run the hybrid tour is shorter yet crosses lines with a higher total
modeled loss. That is a genuine finding, and it is reported as-is rather than
smoothed over.

Making energy loss part of the optimization objective would be a different
change, and is not this one.

---

## 8. Where the code lives

| Path | Role |
|---|---|
| `energy_cost/tariff.py` | The verified rate, its provenance, and the MW→kWh→₹ conversions. |
| `energy_cost/route_loss.py` | Route → lines → loss → money, and the NN vs hybrid comparison. |
| `energy_cost/recompute.py` | Owns the two derived CSV columns. |
| `backend/app/schemas/energy.py` | Response models for the `energy` block. |
| `backend/app/services/serialize.py` | Reshaping only; no figure is recomputed there. |
| `tests/test_energy_cost.py` | Arithmetic, aggregation, edge cases, regression guards. |
| `backend/tests/test_energy_api.py` | The same, as `/solve/compare` returns it. |

The `energy` block appears on `POST /solve/compare`.
