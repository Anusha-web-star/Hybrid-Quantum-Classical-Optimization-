# data/

The dataset lives here. Phase 1 auto-detects the single `*.csv` in this folder
(currently `transmition_lines.csv.csv`); pass `--data PATH` to override.

This file is the single source of truth for the network. Nothing in this project
generates, fabricates, or substitutes network data.

Columns used:

| Column | Role in Phase 1 |
|--------|-----------------|
| `Source`, `Destination` | station names — the graph nodes and edges |
| `Distance_km` | **the TSP route cost** |
| `Source_/Destination_Latitude/Longitude` | map positions |
| `Type` | station label on the map |
| `Voltage_kV`, `Capacity_MW`, `Loss_Percent`, `Energy_Loss_MW` | carried through untouched; `Energy_Loss_MW` is what the route loss costing sums |

Two further columns are **calculated**, not source data, and are appended after
every column above:

| Column | Definition |
|--------|------------|
| `Loss_Cost_Per_Hour_INR` | `Energy_Loss_MW x 1000 x 6.60` |
| `Loss_Cost_Per_Year_INR` | hourly cost `x 8760` - an annualised **estimate** |

They are owned by `python -m energy_cost.recompute`, which rewrites them without
touching a single source value. The rate is the verified KERC HT-2(a) energy
charge; `../DATASET.md` documents the order, the formulas, the 8,760-hour
assumption and what the rate excludes.

The CSV itself is intentionally not committed (see the entry in `.gitignore`
if you decide to exclude it).
