"""Compatibility wrapper for running Chan Master from a source checkout."""

try:
    from chan_master.cli import main
except ModuleNotFoundError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from chan_master.cli import main


if __name__ == "__main__":
    main()
