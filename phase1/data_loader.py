"""Load and validate the transmission-line dataset.

The CSV is the single source of truth. This module reads it, checks the columns
it actually needs, and reports anything questionable instead of silently
dropping stations or connections.

Observed schema (data/transmition_lines.csv.csv):

    Source, Destination, Type,
    Source_Latitude, Source_Longitude,
    Destination_Latitude, Destination_Longitude,
    Distance_km, Voltage_kV, Capacity_MW, Loss_Percent, Energy_Loss_MW

`Distance_km` is the routing cost. `Capacity_MW` / `Loss_Percent` /
`Energy_Loss_MW` / `Voltage_kV` are carried through untouched for the later
energy-loss phase; Phase 1 only records how complete they are.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

# Columns Phase 1 cannot work without.
REQUIRED_COLUMNS = ("Source", "Destination", "Distance_km")

# Columns used for plotting when present.
COORDINATE_COLUMNS = (
    "Source_Latitude",
    "Source_Longitude",
    "Destination_Latitude",
    "Destination_Longitude",
)

# Carried through for later energy-loss estimation. Never required.
ATTRIBUTE_COLUMNS = ("Voltage_kV", "Capacity_MW", "Loss_Percent", "Energy_Loss_MW")


class DatasetError(Exception):
    """The dataset is missing or structurally unusable."""


@dataclass
class Station:
    """One node of the network, as named in the CSV."""

    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    types: set = field(default_factory=set)

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def type_label(self) -> str:
        return "/".join(sorted(self.types)) if self.types else "unknown"


@dataclass
class Connection:
    """One transmission line, as listed in the CSV (treated as undirected)."""

    source: str
    destination: str
    distance_km: Optional[float]
    voltage_kv: Optional[float] = None
    capacity_mw: Optional[float] = None
    loss_percent: Optional[float] = None
    energy_loss_mw: Optional[float] = None
    line_type: Optional[str] = None
    row_number: int = 0

    @property
    def is_routable(self) -> bool:
        """Usable as a TSP edge only if it carries a positive distance."""
        return self.distance_km is not None and self.distance_km > 0


@dataclass
class Dataset:
    """Everything Phase 1 needs, straight from the CSV."""

    path: str
    stations: dict            # name -> Station
    connections: list         # list[Connection], every row kept
    warnings: list            # list[str], issues found but not fatal
    raw: pd.DataFrame

    @property
    def station_names(self) -> list:
        return sorted(self.stations)

    @property
    def routable_connections(self) -> list:
        return [c for c in self.connections if c.is_routable]

    def attribute_coverage(self) -> dict:
        """How many connections carry each optional attribute.

        Phase 1 does not estimate energy loss; this just records what the later
        phase will have to work with.
        """
        total = len(self.connections)
        coverage = {}
        for attr, field_name in (
            ("Voltage_kV", "voltage_kv"),
            ("Capacity_MW", "capacity_mw"),
            ("Loss_Percent", "loss_percent"),
            ("Energy_Loss_MW", "energy_loss_mw"),
        ):
            present = sum(
                1 for c in self.connections if getattr(c, field_name) is not None
            )
            coverage[attr] = (present, total)
        return coverage


def find_dataset(data_dir: str = "data") -> str:
    """Locate the CSV inside `data/`. Errors instead of guessing when unclear."""
    if not os.path.isdir(data_dir):
        raise DatasetError(f"Data folder not found: {data_dir!r}")

    candidates = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    if not candidates:
        raise DatasetError(f"No .csv file found in {data_dir!r}")
    if len(candidates) > 1:
        names = ", ".join(os.path.basename(c) for c in candidates)
        raise DatasetError(
            f"Multiple CSV files in {data_dir!r} ({names}). "
            f"Pass one explicitly with --data."
        )
    return candidates[0]


def _to_float(value) -> Optional[float]:
    """Parse a cell into a float, or None when it is blank/unparseable."""
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_name(value) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    name = str(value).strip()
    return name or None


def _record_endpoint(
    stations: dict, name: str, lat, lon, line_type, warnings: list, row_number: int
) -> None:
    """Add or update a station from one endpoint of a CSV row."""
    station = stations.get(name)
    if station is None:
        station = Station(name=name)
        stations[name] = station

    if line_type:
        station.types.add(line_type)

    lat, lon = _to_float(lat), _to_float(lon)
    if lat is None or lon is None:
        return

    if not station.has_coordinates:
        station.latitude, station.longitude = lat, lon
    elif (
        abs(station.latitude - lat) > 1e-4 or abs(station.longitude - lon) > 1e-4
    ):
        # Keep the first reading; just say so rather than picking silently.
        warnings.append(
            f"Row {row_number}: '{name}' has conflicting coordinates "
            f"({lat}, {lon}) vs ({station.latitude}, {station.longitude}); "
            f"keeping the first."
        )


def load_dataset(path: Optional[str] = None, data_dir: str = "data") -> Dataset:
    """Read, validate and structure the dataset.

    Nothing is dropped for having missing values. A row is only excluded from
    *routing* if it has no usable `Distance_km`, and that exclusion is reported
    as a warning; the connection itself is still kept in `Dataset.connections`.
    """
    path = path or find_dataset(data_dir)
    if not os.path.isfile(path):
        raise DatasetError(f"Dataset file not found: {path!r}")

    try:
        frame = pd.read_csv(path)
    except Exception as exc:  # malformed CSV, bad encoding, ...
        raise DatasetError(f"Could not read {path!r}: {exc}") from exc

    frame.columns = [str(c).strip() for c in frame.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise DatasetError(
            f"{os.path.basename(path)} is missing required column(s): "
            f"{', '.join(missing)}. Found: {', '.join(frame.columns)}"
        )

    if frame.empty:
        raise DatasetError(f"{os.path.basename(path)} contains no data rows.")

    warnings: list = []
    for column in COORDINATE_COLUMNS:
        if column not in frame.columns:
            warnings.append(
                f"Column '{column}' is absent; the map view will be limited."
            )

    stations: dict = {}
    connections: list = []
    seen_pairs: dict = {}

    for index, row in frame.iterrows():
        row_number = int(index) + 2  # +1 for 0-index, +1 for the header line

        source = _clean_name(row.get("Source"))
        destination = _clean_name(row.get("Destination"))
        if source is None or destination is None:
            warnings.append(
                f"Row {row_number}: blank Source or Destination; row skipped."
            )
            continue
        if source == destination:
            warnings.append(
                f"Row {row_number}: '{source}' connects to itself; "
                f"kept as a station, ignored as a route edge."
            )

        line_type = _clean_name(row.get("Type"))
        _record_endpoint(
            stations, source, row.get("Source_Latitude"),
            row.get("Source_Longitude"), line_type, warnings, row_number,
        )
        # `Type` describes the source facility, so it is not copied to the
        # destination; the destination picks up its own type from its own rows.
        _record_endpoint(
            stations, destination, row.get("Destination_Latitude"),
            row.get("Destination_Longitude"), None, warnings, row_number,
        )

        distance = _to_float(row.get("Distance_km"))
        if distance is None:
            warnings.append(
                f"Row {row_number}: '{source}' -> '{destination}' has no "
                f"Distance_km; connection kept but not usable for routing."
            )
        elif distance <= 0:
            warnings.append(
                f"Row {row_number}: '{source}' -> '{destination}' has "
                f"Distance_km={distance}; connection kept but not usable "
                f"for routing."
            )
            distance = None

        connection = Connection(
            source=source,
            destination=destination,
            distance_km=distance,
            voltage_kv=_to_float(row.get("Voltage_kV")),
            capacity_mw=_to_float(row.get("Capacity_MW")),
            loss_percent=_to_float(row.get("Loss_Percent")),
            energy_loss_mw=_to_float(row.get("Energy_Loss_MW")),
            line_type=line_type,
            row_number=row_number,
        )
        connections.append(connection)

        key = tuple(sorted((source, destination)))
        if key in seen_pairs and source != destination:
            warnings.append(
                f"Row {row_number}: duplicate connection "
                f"'{source}' <-> '{destination}' (also row {seen_pairs[key]}); "
                f"both kept, the shortest is used for routing."
            )
        else:
            seen_pairs[key] = row_number

    if not stations:
        raise DatasetError(f"No usable stations found in {os.path.basename(path)}.")

    no_coords = [s.name for s in stations.values() if not s.has_coordinates]
    if no_coords:
        warnings.append(
            f"{len(no_coords)} station(s) have no coordinates and will be "
            f"placed automatically on the map: {', '.join(sorted(no_coords))}"
        )

    return Dataset(
        path=path,
        stations=stations,
        connections=connections,
        warnings=warnings,
        raw=frame,
    )
