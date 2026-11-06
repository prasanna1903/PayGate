"""Compatibility entry point for ``python -m backend.generator``."""

from backend.generator.cli import main
from backend.generator.generate import EMPLOYEE_COUNTS, GenerationSummary, generate_dataset

__all__ = ["EMPLOYEE_COUNTS", "GenerationSummary", "generate_dataset", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
