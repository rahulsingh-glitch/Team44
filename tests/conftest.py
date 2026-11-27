"""Test support: make repo root and scripts/ importable.

`scripts/` is not a package, so tests load `generate_synthetic_data` by putting
the repo root and scripts/ on sys.path. This file adds no fixtures of its own
beyond path setup; it does not touch feature code.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
