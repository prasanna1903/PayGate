"""Command-line interface for generating PayGate datasets."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from backend.generator.config import load_config
from backend.generator.generate import EMPLOYEE_COUNTS, generate_dataset


def main(arguments: Sequence[str] | None = None) -> int:
    """Parse generation options and run the deterministic pipeline."""
    parser = argparse.ArgumentParser(description="Generate synthetic PayGate data.")
    parser.add_argument(
        "--seed",
        type=int,
        help="Seed for the single NumPy random generator.",
    )
    parser.add_argument(
        "--employees",
        type=int,
        help="Employee count; 200 is starter and 3000 is full.",
    )
    parser.add_argument(
        "--size",
        choices=tuple(EMPLOYEE_COUNTS),
        help="Backward-compatible dataset size shortcut.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Output directory for paygate.db, manifest.json, and ground-truth labels.",
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        help="Backward-compatible override for the SQLite database path.",
    )
    options = parser.parse_args(arguments)
    if options.out is not None and options.database_path is not None:
        parser.error("--out and --database-path cannot be used together")

    config = load_config()
    if options.seed is not None:
        config = replace(config, seed=options.seed)
    if options.size is not None and options.employees is not None:
        parser.error("Use either --size or --employees, not both")

    employee_count = options.employees
    if options.size is not None:
        employee_count = EMPLOYEE_COUNTS[options.size]
    if employee_count is None:
        employee_count = EMPLOYEE_COUNTS["starter"]
    if employee_count < 1:
        parser.error("--employees must be a positive integer")

    summary = generate_dataset(
        config=config,
        employee_count=employee_count,
        output_dir=options.out,
        database_path=options.database_path,
    )
    print(
        f"Generated {summary.size} dataset with {summary.employee_count} employees "
        f"using seed {summary.seed}."
    )
    for table, count in summary.table_counts.items():
        print(f"{table}: {count}")
    print(
        "time_entry + allowance + deduction: "
        f"{summary.time_entry_allowance_deduction_count}"
    )
    print(f"Database: {summary.database_path}")
    print(f"Ground truth: {summary.ground_truth_path}")
    print(f"Manifest: {summary.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
