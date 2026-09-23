"""Building, saving and loading the knowledge base.

The index is a single JSON file of chunks plus a small manifest saying what went
into it and when. It is a derived artefact: deleting it costs nothing, because
`python reindex_assistant.py` rebuilds it from the CSV and the documents, which
remain the only sources of truth.

The index is loaded once per process and cached. `reindex` clears that cache, so
a rebuild takes effect without a restart.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.assistant.documents import Chunk
from app.assistant.retrieval import Bm25Retriever
from app.assistant.sources import build_chunks
from app.core.config import get_settings
from app.dataio.network import get_dataset, get_network

#: Bumped when the chunk shape changes in a way that makes an older file stale.
#: v2 added the project-knowledge primer and the source-code layer.
INDEX_VERSION = 2


class IndexUnavailable(Exception):
    """The knowledge base has not been built, or cannot be read."""


class KnowledgeBase:
    """The built index plus the retriever over it."""

    def __init__(self, chunks: list, manifest: dict):
        self.chunks = chunks
        self.manifest = manifest
        self.retriever = Bm25Retriever(chunks)

    def __len__(self) -> int:
        return len(self.chunks)

    @property
    def counts(self) -> dict:
        counts: dict = {}
        for chunk in self.chunks:
            counts[chunk.kind] = counts.get(chunk.kind, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {
            "version": INDEX_VERSION,
            "manifest": self.manifest,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }


def build() -> KnowledgeBase:
    """Ingest the project's data and documents into a fresh knowledge base."""
    dataset = get_dataset()
    network = get_network()
    chunks, missing = build_chunks(dataset, network)

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_path": str(dataset.path),
        "stations": len(network.names),
        "transmission_lines": len(dataset.routable_connections),
        "csv_rows": len(dataset.connections),
        "chunks": len(chunks),
        "code_files_indexed": len({
            chunk.metadata.get("file") for chunk in chunks if chunk.kind == "code"
        }),
        "documents_missing": missing,
    }
    return KnowledgeBase(chunks, manifest)


def save(knowledge: KnowledgeBase, path: Optional[Path] = None) -> Path:
    """Write the knowledge base to disk, creating the folder if needed."""
    target = Path(path or get_settings().assistant_index_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(knowledge.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def load(path: Optional[Path] = None) -> KnowledgeBase:
    """Read a previously built knowledge base. Raises `IndexUnavailable`."""
    target = Path(path or get_settings().assistant_index_path)
    if not target.is_file():
        raise IndexUnavailable(
            f"No knowledge base at {target}. Build it with: "
            f"python reindex_assistant.py"
        )

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndexUnavailable(f"The knowledge base at {target} is unreadable: {exc}") from exc

    if data.get("version") != INDEX_VERSION:
        raise IndexUnavailable(
            f"The knowledge base at {target} was built by an older version "
            f"(v{data.get('version')}, expected v{INDEX_VERSION}). Rebuild it "
            f"with: python reindex_assistant.py"
        )

    chunks = [Chunk.from_dict(entry) for entry in data.get("chunks", [])]
    if not chunks:
        raise IndexUnavailable(f"The knowledge base at {target} is empty. Rebuild it.")

    return KnowledgeBase(chunks, data.get("manifest", {}))


# --- process-wide cache ----------------------------------------------------
# lru_cache is deliberately not used: it would also cache the IndexUnavailable
# path, so building the index would not take effect until a restart.
_cached: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """The loaded knowledge base, read from disk once per process.

    Falls back to building in memory when no file exists, so a fresh checkout
    answers correctly instead of erroring - the file is an optimization, not a
    prerequisite. Nothing is written as a side effect of a request.
    """
    global _cached
    if _cached is None:
        try:
            _cached = load()
        except IndexUnavailable:
            _cached = build()
    return _cached


def clear_cache() -> None:
    """Drop the cached knowledge base so the next request reloads it."""
    global _cached
    _cached = None


def reindex(path: Optional[Path] = None) -> tuple:
    """Rebuild the knowledge base, write it, and refresh the cache.

    Returns `(knowledge_base, written_path)`.
    """
    global _cached
    knowledge = build()
    written = save(knowledge, path)
    _cached = knowledge
    return knowledge, written
