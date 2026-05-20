#!/usr/bin/env python3
"""Convenience entry point: run ``python main.py`` from this project."""

import sys
from pathlib import Path

# Add the parent of this package to sys.path so the package is importable.
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from cli import main

main()
