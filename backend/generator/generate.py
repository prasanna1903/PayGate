"""Compatibility facade for the modular PayGate data-generation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

import numpy as np

from backend.db.connection import get_connection
from backend.generator.anomalies import inject_anomalies, write_ground_truth
from backend.generator.config import GeneratorConfig, load_config
from backend.generator.derived import aggregate_payroll_inputs
from backend.generator.export import create_baseline_exports
from backend.generator.master import MASTER_TABLES, PROJECT_ROOT, build_master_data
from backend.generator.transactions import TRANSACTION_TABLES, build_transactions


SCHEMA_PATH = PROJECT_ROOT / "backend" / "db" / "schema.sql"
EMPLOYEE_COUNTS = {"starter": 200, "full": 3000}
ALL_TABLES = (
    "employee",
    "pay_group",
    "pay_period",
    "paygroup_period_calendar",
    "leave_record",
    "time_entry",
    "allowance_type",
    "deduction_type",
    "employee_allowance_eligibility",
    "employee_deduction_enrollment",
    "allowance",
    "deduction",
    "payroll_input",
    "payroll_input_source",
    "validation_rule",
    "validation_run",
    "exception",
    "approval",
    "payroll_export",
    "payroll_export_line",
    "state_event",
)


@dataclass(frozen=True)
class GenerationSummary:
    """Paths, checksum, and table counts for one generation run."""

    size: str
    employee_count: int
    seed: int
    table_counts: dict[str, int]
    database_path: Path
    ground_truth_path: Path
    manifest_path: Path
    checksums: dict[str, str]

    @property
    def time_entry_allowance_deduction_count(self) -> int:
        """Return the blueprint's high-volume transaction total."""
        return sum(
            self.table_counts.get(table, 0)
            for table in ("time_entry", "allowance", "deduction")
        )


def _insert_rows(
    connection: sqlite3.Connection,
    table: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    columns = tuple(rows[0])
    if any(tuple(row) != columns for row in rows):
        raise ValueError(f"Inconsistent generated columns for {table}")
    quoted = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    connection.executemany(
        f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
        (tuple(row[column] for column in columns) for row in rows),
    )


def _insert_generated_data(
    connection: sqlite3.Connection,
    master_tables: dict[str, list[dict[str, Any]]],
    transaction_tables: dict[str, list[dict[str, Any]]],
) -> None:
    for table in MASTER_TABLES:
        _insert_rows(connection, table, master_tables[table])
    for table in TRANSACTION_TABLES:
        if table in ("approval", "state_event"):
            continue
        _insert_rows(connection, table, transaction_tables[table])
    _insert_rows(connection, "approval", transaction_tables["approval"])
    _insert_rows(connection, "state_event", transaction_tables["state_event"])


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_name(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        if path.parent.name == "ground_truth":
            return f"ground_truth/{path.name}"
        return path.name


def _write_manifest(
    path: Path,
    *,
    config: GeneratorConfig,
    size: str,
    employee_count: int,
    table_counts: dict[str, int],
    checksums: dict[str, str],
) -> None:
    manifest = {
        "seed": config.seed,
        "parameters": {
            "size": size,
            "employee_count": employee_count,
            "pay_periods": list(config.pay_periods),
            "anomaly_plan_full_scale": dict(config.anomaly_plan),
            "transaction_record_target_full": 100000,
            "ground_truth_directory": "ground_truth",
        },
        "row_counts": table_counts,
        "sha256": checksums,
    }
    path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def generate_dataset(
    size: str = "starter",
    *,
    config: GeneratorConfig | None = None,
    database_path: str | Path | None = None,
    employee_count: int | None = None,
    output_dir: str | Path | None = None,
) -> GenerationSummary:
    """Generate a deterministic dataset and external ground-truth labels.

    `database_path` remains supported for older callers. New callers should
    pass `output_dir`, which receives the database, manifest, and a separate
    ground-truth CSV directory.
    """
    normalized_size = size.lower()
    if employee_count is None:
        if normalized_size not in EMPLOYEE_COUNTS:
            raise ValueError("size must be either 'starter' or 'full'")
        count = EMPLOYEE_COUNTS[normalized_size]
    else:
        if (
            isinstance(employee_count, bool)
            or not isinstance(employee_count, int)
            or employee_count < 1
        ):
            raise ValueError("employee_count must be a positive integer")
        count = employee_count
        if normalized_size not in EMPLOYEE_COUNTS:
            normalized_size = "custom"
    if count == EMPLOYEE_COUNTS["starter"]:
        normalized_size = "starter"
    elif count == EMPLOYEE_COUNTS["full"]:
        normalized_size = "full"

    run_config = load_config() if config is None else config
    output_root = Path(output_dir) if output_dir is not None else None
    if output_root is not None:
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = (
            Path(database_path)
            if database_path is not None
            else output_root / "paygate.db"
        )
        ground_truth_path = output_root / "ground_truth" / "labels.csv"
        manifest_path = output_root / "manifest.json"
        checksum_root = output_root
    else:
        output_path = (
            Path(database_path)
            if database_path is not None
            else run_config.database_path
        )
        if database_path is None:
            ground_truth_path = (
                run_config.ground_truth_dir / f"{normalized_size}_labels.csv"
            )
        else:
            ground_truth_path = (
                output_path.parent / "ground_truth" / f"{output_path.stem}_labels.csv"
            )
        manifest_path = output_path.with_suffix(".manifest.json")
        checksum_root = output_path.parent

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(run_config.seed)
    master = build_master_data(count, run_config, rng)
    transactions = build_transactions(master, run_config, rng, count)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}.",
        suffix=".building",
        dir=output_path.parent,
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        connection = get_connection(temporary_path)
        try:
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            with connection:
                _insert_generated_data(connection, master.tables, transactions.tables)
                aggregate_payroll_inputs(connection)
                create_baseline_exports(connection)
                labels = inject_anomalies(
                    connection,
                    run_config,
                    rng,
                    count,
                    transactions.boundary_labels,
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_key_errors = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if integrity != [("ok",)]:
                raise RuntimeError(f"SQLite integrity check failed: {integrity}")
            if foreign_key_errors:
                raise RuntimeError(
                    f"SQLite foreign-key check failed: {foreign_key_errors[:10]}"
                )
            table_counts = {
                table: int(
                    connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                )
                for table in ALL_TABLES
            }
        finally:
            connection.close()

        volume_count = sum(
            table_counts[table] for table in ("time_entry", "allowance", "deduction")
        )
        if count == EMPLOYEE_COUNTS["full"] and not 95000 <= volume_count <= 105000:
            raise RuntimeError(
                "Full dataset transaction volume is outside the blueprint target: "
                f"{volume_count} (expected 95,000 to 105,000)"
            )

        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    write_ground_truth(labels, str(ground_truth_path))
    checksums = {
        _checksum_name(output_path, checksum_root): _checksum(output_path),
        _checksum_name(ground_truth_path, checksum_root): _checksum(ground_truth_path),
    }
    for relative_path in (
        Path("backend") / "db" / "schema.sql",
        Path("data") / "seed" / "pay_groups.csv",
        Path("data") / "seed" / "allowance_types.csv",
        Path("data") / "seed" / "deduction_types.csv",
    ):
        source_path = PROJECT_ROOT / relative_path
        checksums[relative_path.as_posix()] = _checksum(source_path)
    _write_manifest(
        manifest_path,
        config=run_config,
        size=normalized_size,
        employee_count=count,
        table_counts=table_counts,
        checksums=checksums,
    )
    return GenerationSummary(
        size=normalized_size,
        employee_count=count,
        seed=run_config.seed,
        table_counts=table_counts,
        database_path=output_path,
        ground_truth_path=ground_truth_path,
        manifest_path=manifest_path,
        checksums=checksums,
    )
