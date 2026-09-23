"""Ingestion: the project's own data, documentation and code, turned into chunks.

Five families, and nothing else is ever admitted to the knowledge base:

1. PROJECT DATA - the transmission-line CSV, read through the same
   `phase1.data_loader` / `phase1.network` the solvers use. The API does not
   keep a second copy of the network, and neither does this.
2. CURATED DOCUMENTS - files already in this repository: DATASET.md, README.md,
   docs/PHASES.md, data/README.md. No web content is fetched, and nothing is
   added that a maintainer did not write into the project.
3. The tariff record, rendered from `energy_cost.tariff` so the rate the
   assistant quotes and the rate the CSV was computed at cannot drift apart.
4. THE PROJECT KNOWLEDGE PRIMER - `primer.py`. One written explanation per thing
   this project has to be able to explain, in the words a person asks it in.
   Every fact in it is read off this repository; it introduces no new claims.
5. THE SOURCE CODE - `code.py`. An explicit allowlist of this repository's own
   implementation files, split at their own function and class boundaries, so a
   technical question is answered by what the program does rather than only by
   prose about it. `.env` and credentials are not reachable by that module.

Solver outputs are the sixth family and live in `runcontext.py`, because they
belong to one request rather than to the index.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import pandas as pd

from energy_cost.tariff import (HOURS_PER_YEAR,
                                KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE)
from phase1.data_loader import Dataset
from phase1.network import Network

from app.assistant.chunking import chunk_markdown
from app.assistant.code import code_chunks
from app.assistant.documents import Chunk, number
from app.assistant.primer import primer_chunks

#: Repository root: backend/app/assistant/sources.py -> parents[3].
PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Curated documents, in the order they are indexed. Each entry is a repo
#: relative path and the label a citation shows. A file that is not present is
#: skipped and reported - never substituted.
CURATED_DOCUMENTS = (
    ("DATASET.md", "DATASET.md - dataset definition and methodology"),
    ("README.md", "README.md - project overview and methodology"),
    ("docs/PHASES.md", "docs/PHASES.md - phase log and implementation notes"),
    ("data/README.md", "data/README.md - dataset columns"),
)


def _cell(row, column: str) -> Optional[float]:
    """One numeric cell from the raw CSV frame, or None when it is blank."""
    try:
        value = row[column]
    except (KeyError, IndexError, TypeError):
        return None
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slug(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


# ---------------------------------------------------------------------------
# 1. Project data
# ---------------------------------------------------------------------------

def transmission_line_chunks(dataset: Dataset) -> list:
    """One chunk per CSV row: the whole line record, in words.

    Every number is read from the file. `Loss_Cost_Per_Hour_INR` and
    `Loss_Cost_Per_Year_INR` are the CSV's own derived columns, so the assistant
    quotes exactly what `energy_cost.recompute` wrote - it never re-derives a
    figure of its own.
    """
    frame: pd.DataFrame = dataset.raw
    filename = Path(dataset.path).name
    chunks: list = []

    for position, connection in enumerate(dataset.connections):
        row = frame.iloc[position] if position < len(frame) else None
        hourly = _cell(row, "Loss_Cost_Per_Hour_INR") if row is not None else None
        yearly = _cell(row, "Loss_Cost_Per_Year_INR") if row is not None else None
        pair = f"{connection.source} -> {connection.destination}"

        text = "\n".join([
            f"TRANSMISSION LINE (dataset record): {pair}",
            f"CSV row {connection.row_number} of {filename}.",
            f"Source station: {connection.source}",
            f"Destination station: {connection.destination}",
            "Type (facility type of the source station): "
            f"{connection.line_type or 'not recorded in the dataset'}",
            f"Distance_km: {number(connection.distance_km, 'km')}",
            f"Voltage_kV: {number(connection.voltage_kv, 'kV')}",
            f"Capacity_MW: {number(connection.capacity_mw, 'MW')}",
            f"Loss_Percent: {number(connection.loss_percent, '%')}",
            f"Energy_Loss_MW: {number(connection.energy_loss_mw, 'MW')}",
            f"Loss_Cost_Per_Hour_INR: {number(hourly, 'INR per hour', 2)}",
            f"Loss_Cost_Per_Year_INR: {number(yearly, 'INR per year', 2)}",
        ])
        # The standing of these columns - which are source, which are derived,
        # and that all of them are modeled rather than metered - is NOT repeated
        # here. It was, and it cost 645 characters in every one of these 38
        # records against 469 characters of actual fact: retrieving four line
        # records paid for the same caveat four times, and on a local CPU model
        # that duplication is measured in seconds of prompt processing. It is
        # now stated once per request, by `context.DATASET_STANDING`, which
        # every assembled context block carries whenever a dataset record is in
        # it. Same rule, same authority, stated once.

        chunks.append(Chunk(
            id=f"line:{_slug(connection.source)}--{_slug(connection.destination)}",
            kind="dataset",
            title=f"Transmission line: {pair}",
            locator=f"{filename} row {connection.row_number}",
            text=text,
            metadata={
                "source": connection.source,
                "destination": connection.destination,
                "csv_row": connection.row_number,
                "distance_km": connection.distance_km,
                "energy_loss_mw": connection.energy_loss_mw,
                "loss_cost_per_hour_inr": hourly,
                "loss_cost_per_year_inr": yearly,
            },
        ))

    return chunks


def station_chunks(dataset: Dataset, network: Network) -> list:
    """One chunk per station: where it is, what it is, and what it connects to."""
    filename = Path(dataset.path).name
    chunks: list = []

    for name in network.names:
        station = dataset.stations[name]
        neighbours = sorted(network.adjacency[name])
        lines = [
            f"  - {name} <-> {other}: {number(network.adjacency[name][other], 'km')}"
            for other in neighbours
        ]

        text = "\n".join([
            f"STATION (dataset record): {name}",
            f"Type: {station.type_label}",
            f"Latitude: {number(station.latitude, '', 4)}",
            f"Longitude: {number(station.longitude, '', 4)}",
            f"Transmission lines meeting here: {len(neighbours)}",
            "Directly connected stations and the line distance to each:",
            *(lines or ["  - none; this station is isolated in the dataset"]),
        ])

        chunks.append(Chunk(
            id=f"station:{_slug(name)}",
            kind="dataset",
            title=f"Station: {name}",
            locator=f"{filename} (station record)",
            text=text,
            metadata={"station": name, "degree": len(neighbours)},
        ))

    return chunks


def network_summary_chunk(dataset: Dataset, network: Network) -> Chunk:
    """The shape of the whole graph, so scale questions have a grounded answer."""
    summary = network.summary()
    coverage = dataset.attribute_coverage()
    coverage_lines = [
        f"  - {column}: present on {present} of {total} CSV rows"
        for column, (present, total) in coverage.items()
    ]

    text = "\n".join([
        "NETWORK SUMMARY (dataset record).",
        f"Dataset file: {Path(dataset.path).name}",
        f"Stations: {summary['stations']}",
        f"Rows in the CSV: {summary['rows_in_csv']}",
        "Routable transmission lines (positive Distance_km): "
        f"{summary['routable_lines']}",
        f"Connected components: {summary['components']}",
        f"Graph is fully connected: {network.is_connected}",
        f"Isolated stations: {', '.join(summary['isolated']) or 'none'}",
        f"Shortest line: {number(summary['shortest_line_km'], 'km')}",
        f"Longest line: {number(summary['longest_line_km'], 'km')}",
        f"Total line length in the dataset: {number(summary['total_line_km'], 'km')}",
        "Optional-attribute coverage:",
        *coverage_lines,
        "",
        "This graph represents an electricity transmission network. The TSP "
        "optimization in this project uses the route-distance objective "
        "(Distance_km) only. The electrical parameters above let the resulting "
        "routes be EVALUATED for energy implications afterwards; they are not "
        "part of the optimization cost.",
    ])

    return Chunk(
        id="network:summary",
        kind="dataset",
        title="Network summary",
        locator=f"{Path(dataset.path).name} (whole-file summary)",
        text=text,
        metadata={k: v for k, v in summary.items() if not isinstance(v, list)},
    )


def tariff_chunk() -> Chunk:
    """The tariff record, rendered from the module the CSV was computed with.

    Reading it from `energy_cost.tariff` rather than restating it is the point:
    if the project's rate changes, the assistant's answer changes with it, and
    the two can never disagree.
    """
    tariff = KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE
    excludes = "\n".join(f"  - {item}" for item in tariff.excludes)

    # ORDER MATTERS HERE, and not for readability.
    #
    # A retrieved chunk longer than `context.MAX_CHUNK_CHARS` is truncated at
    # the end rather than dropped, so whatever sits last is what disappears
    # first. This chunk used to lead with the citation - order name, URL,
    # accessed date - and put the two things the assistant is REQUIRED to say
    # about money after them. The cap then cut the sentence "annualized values
    # assume continuous modeled operation" in half, which removed a mandatory
    # caveat while leaving the rupee figures intact: the worst possible half to
    # keep.
    #
    # So the obligations come first and the bibliography last. Truncation now
    # costs a URL, never a caveat.
    text = "\n".join([
        "TARIFF AND MONETARY-LOSS BASIS (approved project reference).",
        f"Rate: Rs. {tariff.inr_per_kwh:.2f} per kWh "
        f"({tariff.paise_per_kwh} paise/kWh).",
        f"Category: {tariff.category}",
        f"Component: {tariff.component}",
        "",
        "CALCULATION, exactly as this project defines it:",
        f"  Loss_Cost_Per_Hour_INR = Energy_Loss_MW x 1000 x {tariff.inr_per_kwh:.2f}",
        f"  Loss_Cost_Per_Year_INR = Loss_Cost_Per_Hour_INR x {HOURS_PER_YEAR}",
        "The factor 1000 converts MW held for one hour into kWh. These are the "
        "definitions of the CSV's own derived columns; quote those columns "
        "rather than working the formula yourself.",
        "",
        "THIS IS AN ENERGY CHARGE ONLY. It is the value of the lost energy, "
        "not an electricity bill. It excludes:",
        excludes,
        "",
        "The annual figure assumes the modeled loss is present for all "
        f"{HOURS_PER_YEAR} hours of the year - continuous modeled operation. "
        "The dataset carries no load factor, no generation schedule and no "
        "outage profile, so the annual value is an estimate of what a year at "
        "this constant loss would be worth. It must never be presented as an "
        "actual annual bill or an actual annual loss.",
        "",
        "A figure of Rs. 3.00/kWh has circulated as the March 2025 KERC HT "
        "industrial energy charge. This project checked it against the order "
        "and did not adopt it: the FY2025-26 HT-2(a) energy charge in "
        f"Annexure-9 is {tariff.paise_per_kwh} paise/kWh, and Rs. 3.00/kWh is "
        "not used anywhere in this project. Every rupee figure in the dataset "
        f"and in the API is computed at Rs. {tariff.inr_per_kwh:.2f}/kWh.",
        "",
        "PROVENANCE (least critical if this record is shortened):",
        f"  Order: {tariff.order_name}",
        f"  Authority: {tariff.authority}",
        f"  Order date: {tariff.order_date}",
        f"  Effective period: {tariff.effective_period}",
        f"  Located at: {tariff.source_location}",
        f"  Source URL: {tariff.source_url}",
        f"  Source last checked: {tariff.accessed}",
        f"  Note recorded in the project: {tariff.notes}",
    ])

    return Chunk(
        id="reference:tariff",
        kind="doc",
        title="KERC tariff basis and the monetary-loss calculation",
        locator="energy_cost/tariff.py (rate verified against the KERC order)",
        text=text,
        metadata={"inr_per_kwh": tariff.inr_per_kwh,
                  "hours_per_year": HOURS_PER_YEAR},
    )


def methodology_chunk() -> Chunk:
    """What GRIDOPT does and does not optimize, stated once and unambiguously.

    This exists because it is the single most inviting place for an assistant to
    over-claim. Stating the relationship explicitly in retrievable context is
    what lets the model answer it correctly instead of reasoning towards it.
    """
    text = "\n".join([
        "GRIDOPT OPTIMIZATION OBJECTIVE - what is and is not optimized.",
        "",
        "The graph represents an electricity transmission network.",
        "The TSP optimization uses the project's defined route-distance "
        "objective: Distance_km, and nothing else. Both solvers minimize the "
        "same quantity.",
        "  - The classical solver is Nearest Neighbour (phase1/nn_tsp.py).",
        "  - The hybrid solver is QAOA used as the optimization engine inside "
        "a classical full-network reoptimization loop, started from the "
        "Nearest Neighbour tour (phase2/hybrid.py).",
        "Neither solver optimizes energy loss, loss percentage or cost.",
        "",
        "The transmission electrical parameters (Voltage_kV, Capacity_MW, "
        "Loss_Percent, Energy_Loss_MW) allow the routes the solvers produce to "
        "be EVALUATED for their energy implications after the fact. That "
        "evaluation is what the API's `energy` block reports.",
        "",
        "An energy-aware optimization objective would require explicitly "
        "incorporating energy-loss terms into the optimization cost. That is "
        "not what the current implementation does.",
        "",
        "CONSEQUENCE, stated so it is not misread: a route that is N km "
        "shorter is NOT thereby N km 'less energy loss'. Distance optimization "
        "and energy-loss evaluation are separate. A shorter route can cross "
        "lossier lines and carry MORE modeled loss than a longer one. The only "
        "way to compare two routes on loss is to sum Energy_Loss_MW over the "
        "distinct lines each route actually uses, which is what the energy "
        "analysis does.",
        "",
        "Energy_Loss_MW is summed once per distinct line used, not once per "
        "traversal: it is a property of the line, and a line dissipates it "
        "continuously while energised.",
        "",
        "HOW THE HYBRID QAOA APPROACH WORKS, at the level the code implements:",
        "  1. The classical Nearest Neighbour tour over the full network is "
        "the starting point.",
        "  2. A sliding window of W consecutive stations on that tour is taken "
        "as a subproblem. The cost matrix for those stations comes from the "
        "network's own travel costs - nothing is fabricated.",
        "  3. The subproblem is written as a TSP QUBO with position encoding "
        "x[i][t] and the window start pinned to position 0, giving (W-1)^2 "
        "binary variables; 'exactly one' constraints enter as squared "
        "penalties. The QUBO is mapped to an Ising Hamiltonian (SparsePauliOp "
        "of Z and ZZ terms) and handed to QAOA, whose 2p angles are optimized "
        "by COBYLA against a CVaR objective.",
        "  4. Sampled bitstrings are decoded, every valid sub-tour is scored, "
        "and the reordering is accepted only if it shortens the full tour.",
        "  5. Sweeps repeat until no window improves or the sweep cap is hit.",
        "QAOA is approximate throughout. The project makes no optimality claim "
        "and no quantum-advantage claim.",
    ])

    return Chunk(
        id="reference:objective",
        kind="doc",
        title="What GRIDOPT optimizes (route distance) and how the hybrid QAOA loop works",
        locator="DATASET.md / docs/PHASES.md - project methodology, stated for retrieval",
        text=text,
        metadata={"objective": "route distance (Distance_km)"},
    )


# ---------------------------------------------------------------------------
# 2. Curated documents
# ---------------------------------------------------------------------------

def curated_document_chunks(root: Optional[Path] = None) -> tuple:
    """Chunk the project's own Markdown documentation.

    Returns `(chunks, missing)`. A document that is not on disk is reported in
    `missing` and simply is not indexed; nothing stands in for it.
    """
    base = root or PROJECT_ROOT
    chunks: list = []
    missing: list = []

    for relative, label in CURATED_DOCUMENTS:
        path = base / relative
        if not path.is_file():
            missing.append(relative)
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        for position, (trail, body) in enumerate(chunk_markdown(text)):
            heading = trail or "(document root)"
            chunks.append(Chunk(
                id=f"doc:{_slug(relative)}:{position}",
                kind="doc",
                title=f"{label} - {heading}" if trail else label,
                locator=f"{relative} - {heading}",
                text=f"PROJECT DOCUMENTATION, {relative} ({heading}):\n\n{body}",
                metadata={"file": relative, "heading": heading},
            ))

    return chunks, missing


# ---------------------------------------------------------------------------
# The whole ingestion
# ---------------------------------------------------------------------------

def build_chunks(dataset: Dataset, network: Network,
                 root: Optional[Path] = None) -> tuple:
    """Every indexable chunk, plus the list of files that were not found.

    Order is fixed and the builders are deterministic, so re-indexing the same
    working tree produces the same chunks with the same ids in the same order.
    """
    documents, missing_docs = curated_document_chunks(root)
    source_code, missing_code = code_chunks(root)
    chunks = [
        network_summary_chunk(dataset, network),
        methodology_chunk(),
        tariff_chunk(),
        *primer_chunks(),
        *transmission_line_chunks(dataset),
        *station_chunks(dataset, network),
        *documents,
        *source_code,
    ]
    return chunks, [*missing_docs, *missing_code]
