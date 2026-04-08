#!/usr/bin/env python3
"""Launch the OpenCROW Constellation filesystem watcher."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SEARCH_PATHS = [SCRIPT_DIR, SCRIPT_DIR.parent]
for candidate in SEARCH_PATHS:
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from constellation.watcher import main


if __name__ == "__main__":
    raise SystemExit(main())
