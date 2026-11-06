"""Compatibility entry point for the blueprint command ``python -m generator.cli``."""

from backend.generator.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
