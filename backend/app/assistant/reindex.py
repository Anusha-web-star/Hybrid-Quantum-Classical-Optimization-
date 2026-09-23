"""Rebuild the assistant's knowledge base.

Run it from the repository root:

    python reindex_assistant.py

or, equivalently, as a module with `backend` on the path:

    python -m app.assistant.reindex

Re-run it whenever anything it indexes changes: a new CSV, a tariff change
followed by `python -m energy_cost.recompute`, an edit to DATASET.md, README.md
or docs/PHASES.md, a change to the project knowledge in `primer.py`, or a change
to one of the source files on the allowlist in `code.py`. The index is derived,
so rebuilding it is always safe, and two builds of the same working tree produce
byte-for-byte the same chunks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="reindex_assistant",
        description="Rebuild the GRIDOPT assistant knowledge base from the "
                    "project's dataset and documentation.",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Write the index here instead of the configured location.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build and report, without writing the file.",
    )
    args = parser.parse_args(argv)

    from phase1.data_loader import DatasetError

    from app.assistant import index as index_module

    try:
        if args.dry_run:
            knowledge = index_module.build()
            written = None
        else:
            knowledge, written = index_module.reindex(args.out)
    except DatasetError as exc:
        print(f"Cannot build the knowledge base: {exc}", file=sys.stderr)
        return 1

    manifest = knowledge.manifest
    print("GRIDOPT assistant knowledge base")
    print(f"  dataset            {manifest.get('dataset_path')}")
    print(f"  stations           {manifest.get('stations')}")
    print(f"  csv rows           {manifest.get('csv_rows')}")
    print(f"  routable lines     {manifest.get('transmission_lines')}")
    print(f"  source files       {manifest.get('code_files_indexed')}")
    print(f"  chunks             {len(knowledge)}")
    for kind, count in sorted(knowledge.counts.items()):
        print(f"    {kind:<16} {count}")

    missing = manifest.get("documents_missing") or []
    if missing:
        print("  documents missing  " + ", ".join(missing))
        print("    (not indexed, and nothing was substituted for them)")

    if written is None:
        print("  dry run            nothing written")
    else:
        print(f"  written to         {written}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
