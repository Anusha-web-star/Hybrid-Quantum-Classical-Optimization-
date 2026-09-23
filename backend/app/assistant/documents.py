"""The unit of retrieval, and what it is allowed to claim about itself.

A `Chunk` is one retrievable piece of GRIDOPT context plus the provenance that
makes it citable. Nothing in this package ever creates a chunk out of thin air:
each one is produced by a builder in `sources.py` or `runcontext.py` from a row
of the CSV, a file on disk, or a solver payload the caller supplied.

`kind` is what the answer cites back to the user:

    dataset   a transmission-line, station or network record from the CSV
    doc       project documentation or approved reference material
    code      a unit of this repository's own source code - a module, class or
              function - indexed from an explicit allowlist of project files
    solver    an actual optimization run's output
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

#: The four source families. `service.py` reports these back as `sources`.
KINDS = ("dataset", "doc", "code", "solver")


@dataclass(frozen=True)
class Chunk:
    """One retrievable piece of grounded project context."""

    #: Stable identifier. Re-indexing the same data produces the same id, so a
    #: citation stays meaningful across rebuilds.
    id: str
    kind: str
    #: Short human label - what the UI shows as the source chip.
    title: str
    #: Where this came from, concretely: a CSV path and row, a filename and
    #: heading, or the run that produced it.
    locator: str
    #: The text handed to the model. Already self-describing: a retrieved chunk
    #: has to make sense on its own, because that is all the model sees.
    text: str
    #: Extra structured facts kept for the response, never for the prompt.
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"Unknown chunk kind {self.kind!r}; expected one of {KINDS}.")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        return cls(
            id=data["id"],
            kind=data["kind"],
            title=data["title"],
            locator=data["locator"],
            text=data["text"],
            metadata=data.get("metadata", {}) or {},
        )


@dataclass(frozen=True)
class ScoredChunk:
    """A chunk a retriever considered relevant, with its score."""

    chunk: Chunk
    score: float


def number(value: Optional[float], unit: str = "", decimals: int = 3) -> str:
    """Format a numeric dataset value, or say plainly that there isn't one."""
    if value is None or (isinstance(value, float) and value != value):
        return "not recorded in the dataset"
    formatted = f"{value:,.{decimals}f}".rstrip("0").rstrip(".")
    return f"{formatted} {unit}".strip()
