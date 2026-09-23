"""Backend application package.

The Phase 1 and Phase 2 solvers live at the repository root, outside this
package. Putting that root on `sys.path` here - before any `app.*` submodule is
imported - lets the API call `phase1` and `phase2` directly, so the classical
Nearest Neighbour solver, the hybrid QAOA reoptimizer and the comparison are
the ones already tested, never a second copy.
"""

import sys
from pathlib import Path

# <repo root>/backend/app/__init__.py -> parents[2] == <repo root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
