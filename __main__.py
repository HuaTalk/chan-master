"""Run Chan Master from this project directory."""

import sys
from pathlib import Path

# Ensure the parent of this package is on sys.path so the module is
# importable even when running from inside the package directory.
_pkg_dir = Path(__file__).resolve().parent
_parent = _pkg_dir.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from cli import main

main()
