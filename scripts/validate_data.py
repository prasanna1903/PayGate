"""Verify generated PayGate datasets and optionally prove reproducibility."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.validation.dataset_checks import (  # noqa: E402
    DatasetReport,
    ReproducibilityReport,
    validate_dataset,
    verify_reproducibility,
)


def _render_summary(
    reports: list[DatasetReport],
    reproducibility: ReproducibilityReport | None,
) -> str:
    lines = ["# PayGate Dataset Validation Summary", ""]
    for report in reports:
        lines.extend(
            (
                f"## {report.dataset_path}",
                "",
                f"- Result: **{'PASS' if report.passed else 'FAIL'}**",
                f"- Seed: {report.seed}",
                f"- Employees: {report.employee_count}",
                f"- Time-entry + allowance + deduction rows: {report.transaction_count}",
                f"- Ground-truth labels: {report.label_count}",
                "",
                "| Check | Result | Detail |",
                "|---|---|---|",
            )
        )
        for check in report.checks:
            detail = check.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {check.name} | {'PASS' if check.passed else 'FAIL'} | {detail} |"
            )
        lines.append("")
    if reproducibility is not None:
        lines.extend(
            (
                "## Reproducibility",
                "",
                f"- Result: **{'PASS' if reproducibility.passed else 'FAIL'}**",
                f"- Seed: {reproducibility.seed}",
                f"- Employees: {reproducibility.employee_count}",
                f"- Detail: {reproducibility.detail}",
                "",
                "| File | SHA-256 |",
                "|---|---|",
            )
        )
        for name, checksum in sorted(reproducibility.checksums.items()):
            lines.append(f"| {name} | `{checksum}` |")
        lines.append("")
    return "\n".join(lines)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run dataset checks and return a failing exit status on any error."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate PayGate starter/full datasets, or regenerate twice "
            "and compare manifest checksums."
        )
    )
    parser.add_argument(
        "datasets",
        nargs="*",
        type=Path,
        help="Dataset directories or database files (default: Module 3 starter and full outputs).",
    )
    parser.add_argument(
        "--repro",
        action="store_true",
        help="Generate two isolated datasets with the same seed and compare checksums.",
    )
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument(
        "--employees",
        type=int,
        choices=(200, 3000),
        default=200,
        help="Reproducibility dataset size (200 starter or 3000 full).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "docs" / "VALIDATION_SUMMARY.md",
        help="Markdown report path (default: docs/VALIDATION_SUMMARY.md).",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Print results without writing the Markdown summary.",
    )
    options = parser.parse_args(arguments)

    dataset_paths = options.datasets
    if not dataset_paths:
        dataset_paths = [
            PROJECT_ROOT / "data" / "module3-starter",
            PROJECT_ROOT / "data" / "module3-full",
        ]
    reports = [validate_dataset(path) for path in dataset_paths]
    for report in reports:
        print(
            f"{'PASS' if report.passed else 'FAIL'} dataset: {report.dataset_path}"
        )
        for check in report.checks:
            print(
                f"  {'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}"
            )

    reproducibility: ReproducibilityReport | None = None
    if options.repro:
        try:
            reproducibility = verify_reproducibility(
                seed=options.seed,
                employee_count=options.employees,
            )
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
            print(f"FAIL reproducibility: {error}", file=sys.stderr)
            return 1
        print(
            f"{'PASS' if reproducibility.passed else 'FAIL'} reproducibility: "
            f"{reproducibility.detail}"
        )

    failed = any(not report.passed for report in reports) or (
        reproducibility is not None and not reproducibility.passed
    )
    if not options.no_report:
        try:
            options.report.parent.mkdir(parents=True, exist_ok=True)
            options.report.write_text(
                _render_summary(reports, reproducibility),
                encoding="utf-8",
                newline="\n",
            )
            print(f"Validation summary: {options.report}")
        except OSError as error:
            print(f"FAIL writing validation summary {options.report}: {error}", file=sys.stderr)
            failed = True
    if failed:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
