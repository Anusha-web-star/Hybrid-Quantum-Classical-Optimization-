"""Rebuild the GRIDOPT assistant's knowledge base.

    python reindex_assistant.py
    python reindex_assistant.py --dry-run

Re-run this whenever the project data changes - a new CSV, a tariff change
followed by `python -m energy_cost.recompute`, or an edit to DATASET.md,
README.md, docs/PHASES.md or data/README.md.

`backend/` is put on the path here for the same reason `pytest.ini` does it: the
API package lives there and imports as `app.*`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.assistant.reindex import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    raise SystemExit(main())
