"""Response models for the station and network endpoints."""

from typing import Optional

from pydantic import BaseModel, Field


class StationOut(BaseModel):
    """One station, exactly as the CSV names it."""

    name: str = Field(..., examples=["Mysuru Substation"])
    type: str = Field(..., description="Station type from the CSV, or 'unknown'.")
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    connections: int = Field(
        ..., description="Transmission lines meeting at this station."
    )


class StationListOut(BaseModel):
    count: int
    stations: list[StationOut]


class TransmissionLineOut(BaseModel):
    """One routable transmission line, undirected."""

    source: str
    destination: str
    distance_km: float
    voltage_kv: Optional[float] = None
    capacity_mw: Optional[float] = None
    loss_percent: Optional[float] = None
    energy_loss_mw: Optional[float] = None


class NetworkSummaryOut(BaseModel):
    stations: int
    rows_in_csv: int
    routable_lines: int
    components: int
    connected: bool
    isolated: list[str]
    shortest_line_km: Optional[float] = None
    longest_line_km: Optional[float] = None
    total_line_km: float


class NetworkOut(BaseModel):
    """The whole network: what was loaded, its shape, and every line in it."""

    dataset_path: str
    summary: NetworkSummaryOut
    stations: list[StationOut]
    transmission_lines: list[TransmissionLineOut]


class StartStationOut(BaseModel):
    """A starting station, resolved to its exact name in the dataset."""

    requested: str
    resolved: str
    matched_exactly: bool
