"""Console-less source launcher for BetterShutup.

Keeping the launcher inside the package lets Nuitka compile the complete
application from a single source tree while still allowing direct
double-click execution from this folder.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from better_shutup.app import main

if __name__ == "__main__":
    raise SystemExit(main())
