"""Verify generated PayGate datasets against their manifest and invariants."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
from typing import Any

from backend.db.connection import get_connection
from backend.generator.config import load_config
from backend.generator.generate import GenerationSummary, generate_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = frozenset(
    {
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
    }
)
REQUIRED_CHECKSUMS = frozenset(
    {
        "backend/db/schema.sql",
        "data/seed/pay_groups.csv",
        "data/seed/allowance_types.csv",
        "data/seed/deduction_types.csv",
    }
)
GROUND_TRUTH_COLUMNS = (
    "gt_id",
    "issue_type",
    "entity_type",
    "entity_id",
    "employee_id",
    "period_id",
    "expected_rule_id",
    "expected_decision",
    "severity",
    "injected_by",
    "description",
)
ISSUE_RULES = {
    "hours_exceed_period_max": ("VR-004", "High", "FLAG"),
    "duplicate_allowance": ("VR-006", "High", "FLAG"),
    "unapproved_time_exported": ("VR-008", "Critical", "FLAG"),
    "leave_deduction_applied_twice": ("VR-007", "High", "FLAG"),
    "totals_fail_to_reconcile": ("VR-009", "Critical", "FLAG"),
    "missing_bank": ("VR-001", "High", "FLAG"),
    "missing_tax": ("VR-002", "High", "FLAG"),
    "duplicate_hours": ("VR-003", "High", "FLAG"),
    "outlier_hours": ("VR-005", "Medium", "FLAG"),
    "boundary_exact_max_hours": ("VR-004", "High", "PASS"),
    "boundary_legitimate_correction": ("VR-003", "High", "PASS"),
    "boundary_legitimate_resubmission": ("VR-003", "High", "PASS"),
}
ISSUE_ENTITY_TYPES = {
    "hours_exceed_period_max": "payroll_input",
    "duplicate_allowance": "allowance",
    "unapproved_time_exported": "time_entry",
    "leave_deduction_applied_twice": "deduction",
    "totals_fail_to_reconcile": "payroll_export_line",
    "missing_bank": "employee",
    "missing_tax": "employee",
    "duplicate_hours": "time_entry",
    "outlier_hours": "time_entry",
    "boundary_exact_max_hours": "payroll_input",
    "boundary_legitimate_correction": "time_entry",
    "boundary_legitimate_resubmission": "time_entry",
}
REQUIRED_FULL_ANOMALY_COUNTS = {
    "hours_exceed_period_max": 40,
    "duplicate_allowance": 30,
    "unapproved_time_exported": 15,
    "leave_deduction_applied_twice": 25,
    "totals_fail_to_reconcile": 10,
}
ID_PATTERNS = {
    "employee": re.compile(r"EMP-\d{6,}\Z"),
    "pay_group": re.compile(r"PG-\d{3,}\Z"),
    "pay_period": re.compile(r"PP-\d{4}-\d{2}\Z"),
    "leave_record": re.compile(r"LV-\d{6,}\Z"),
    "time_entry": re.compile(
        r"TIME-(EMP-\d{6,})-(\d{4}-\d{2}-\d{2})(?:-R([12]))?\Z"
    ),
    "allowance": re.compile(r"ALW-\d{6,}\Z"),
    "deduction": re.compile(r"DED-\d{6,}\Z"),
    "allowance_type": re.compile(r"ALT-\d{3,}\Z"),
    "deduction_type": re.compile(r"DET-\d{3,}\Z"),
    "payroll_input": re.compile(r"PIN-(EMP-\d{6,})-(\d{4})-(\d{2})\Z"),
    "validation_rule": re.compile(r"VR-\d{3,}\Z"),
    "exception": re.compile(r"EXC-\d{6,}\Z"),
    "approval": re.compile(r"APR-\d{6,}\Z"),
    "state_event": re.compile(r"EVT-\d{6,}\Z"),
    "validation_run": re.compile(r"RUN-\d{6,}\Z"),
    "payroll_export": re.compile(r"PEX-(\d{4})-(\d{6,})\Z"),
}
ID_TABLES = {
    "employee": ("employee", "employee_id"),
    "pay_group": ("pay_group", "pay_group_id"),
    "pay_period": ("pay_period", "period_id"),
    "leave_record": ("leave_record", "leave_id"),
    "time_entry": ("time_entry", "time_entry_id"),
    "allowance": ("allowance", "allowance_id"),
    "deduction": ("deduction", "deduction_id"),
    "payroll_input": ("payroll_input", "payroll_input_id"),
    "validation_rule": ("validation_rule", "rule_id"),
    "exception": ("exception", "exception_id"),
    "approval": ("approval", "approval_id"),
    "state_event": ("state_event", "event_id"),
    "validation_run": ("validation_run", "run_id"),
    "payroll_export": ("payroll_export", "export_id"),
    "allowance_type": ("allowance_type", "allowance_type_id"),
    "deduction_type": ("deduction_type", "deduction_type_id"),
}
DATE_COLUMNS = {
    "employee": ("hire_date", "termination_date", "effective_from", "effective_to"),
    "pay_period": ("start_date", "end_date"),
    "paygroup_period_calendar": ("cutoff_date", "pay_date"),
    "leave_record": ("start_date", "end_date"),
    "time_entry": ("work_date",),
    "employee_allowance_eligibility": ("effective_from", "effective_to"),
    "employee_deduction_enrollment": ("effective_from", "effective_to"),
}
DATETIME_COLUMNS = {
    "time_entry": ("submitted_at",),
    "validation_run": ("started_at",),
    "approval": ("decided_at",),
    "exception": ("created_at",),
    "payroll_export": ("created_at",),
    "state_event": ("occurred_at",),
}
@dataclass(frozen=True)
class CheckResult:
    """One named validation result."""

    name: str
    passed: bool
    detail: str


@dataclass
class DatasetReport:
    """Results and selected metrics for a dataset validation run."""

    dataset_path: Path
    checks: list[CheckResult] = field(default_factory=list)
    seed: int | None = None
    employee_count: int | None = None
    transaction_count: int | None = None
    label_count: int | None = None

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(CheckResult(name, passed, detail))


@dataclass(frozen=True)
class ReproducibilityReport:
    """Checksum comparison from two independent generator executions."""

    seed: int
    employee_count: int
    checksums: dict[str, str]
    passed: bool
    detail: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _resolve_dataset_path(dataset_path: str | Path) -> tuple[Path, Path]:
    path = Path(dataset_path)
    if path.is_file() and path.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
        return path.parent, path
    return path, path / "paygate.db"


def _manifest_check(
    report: DatasetReport,
    dataset_root: Path,
    manifest: dict[str, Any],
    database_path: Path,
) -> Path | None:
    checksums = manifest.get("sha256")
    if not isinstance(checksums, dict):
        report.add("manifest checksums", False, "manifest.sha256 must be an object")
        return None

    missing = (
        REQUIRED_CHECKSUMS | {"ground_truth/labels.csv", database_path.name}
    ) - set(checksums)
    if missing:
        report.add(
            "manifest checksum coverage",
            False,
            "missing checksum entries: " + ", ".join(sorted(missing)),
        )
    else:
        report.add(
            "manifest checksum coverage",
            True,
            f"{len(checksums)} files are listed, including database, labels, schema, and seeds",
        )

    ground_truth_path: Path | None = None
    failures: list[str] = []
    for relative_name, expected_hash in sorted(checksums.items()):
        if not isinstance(relative_name, str) or not isinstance(expected_hash, str):
            failures.append("checksum names and values must be strings")
            continue
        relative = PurePosixPath(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            failures.append(f"unsafe checksum path {relative_name!r}")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            failures.append(f"invalid SHA-256 value for {relative_name}")
            continue
        if relative_name == "paygate.db" or (
            len(relative.parts) == 1 and relative.name == database_path.name
        ):
            file_path = database_path
        elif relative_name == "ground_truth/labels.csv":
            file_path = dataset_root.joinpath(*relative.parts)
            ground_truth_path = file_path
        elif relative.parts and relative.parts[0] == "ground_truth":
            file_path = dataset_root.joinpath(*relative.parts)
        else:
            file_path = PROJECT_ROOT.joinpath(*relative.parts)
        try:
            resolved_path = file_path.resolve(strict=True)
        except OSError:
            failures.append(f"missing checksum file {relative_name}")
            continue
        permitted_root = (
            dataset_root.resolve()
            if relative.parts and relative.parts[0] in ("ground_truth", "paygate.db")
            else PROJECT_ROOT.resolve()
        )
        if not resolved_path.is_relative_to(permitted_root):
            failures.append(f"checksum path escapes its data root: {relative_name}")
            continue
        actual_hash = _sha256(resolved_path)
        if actual_hash != expected_hash:
            failures.append(f"SHA-256 mismatch for {relative_name}")
    report.add(
        "manifest SHA-256 checksums",
        not failures,
        "; ".join(failures) if failures else f"verified {len(checksums)} file checksums",
    )
    return ground_truth_path


def _check_manifest_row_counts(
    report: DatasetReport,
    manifest: dict[str, Any],
    actual_counts: dict[str, int],
) -> None:
    row_counts = manifest.get("row_counts")
    if not isinstance(row_counts, dict):
        report.add("manifest row counts", False, "manifest.row_counts must be an object")
        return
    mismatches = {
        table: (row_counts.get(table), actual)
        for table, actual in actual_counts.items()
        if row_counts.get(table) != actual
    }
    extra_tables = set(row_counts) - set(actual_counts)
    if mismatches or extra_tables:
        details = [
            f"{table}: manifest={expected}, database={actual}"
            for table, (expected, actual) in sorted(mismatches.items())
        ]
        details.extend(f"unexpected manifest table {table}" for table in sorted(extra_tables))
        report.add("manifest row counts", False, "; ".join(details))
    else:
        report.add(
            "manifest row counts",
            True,
            f"all {len(actual_counts)} table counts match",
        )


def _check_table_and_key_integrity(
    connection: sqlite3.Connection,
    report: DatasetReport,
) -> dict[str, int]:
    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    }
    missing_tables = EXPECTED_TABLES - table_names
    extra_tables = table_names - EXPECTED_TABLES
    report.add(
        "operational schema tables",
        not missing_tables and not extra_tables,
        (
            f"found all {len(EXPECTED_TABLES)} operational tables"
            if not missing_tables and not extra_tables
            else f"missing={sorted(missing_tables)}, unexpected={sorted(extra_tables)}"
        ),
    )

    actual_counts: dict[str, int] = {}
    for table in sorted(table_names & EXPECTED_TABLES):
        actual_counts[table] = int(
            connection.execute(f"SELECT count(*) FROM {_quote(table)}").fetchone()[0]
        )

    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    report.add(
        "SQLite integrity",
        integrity == [("ok",)],
        "ok" if integrity == [("ok",)] else "; ".join(str(item[0]) for item in integrity[:10]),
    )
    foreign_key_enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    report.add(
        "foreign-key integrity",
        foreign_key_enabled and not foreign_key_errors,
        (
            "foreign keys enabled; no violations"
            if foreign_key_enabled and not foreign_key_errors
            else f"enabled={foreign_key_enabled}; violations={foreign_key_errors[:10]}"
        ),
    )

    key_failures: list[str] = []
    for table in sorted(table_names & EXPECTED_TABLES):
        columns = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        primary_key = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        if primary_key:
            null_condition = " OR ".join(f"{_quote(column)} IS NULL" for column in primary_key)
            null_count = connection.execute(
                f"SELECT count(*) FROM {_quote(table)} WHERE {null_condition}"
            ).fetchone()[0]
            grouped = ", ".join(_quote(column) for column in primary_key)
            duplicate_count = connection.execute(
                f"SELECT count(*) FROM (SELECT 1 FROM {_quote(table)} "
                f"GROUP BY {grouped} HAVING count(*) > 1)"
            ).fetchone()[0]
            if null_count or duplicate_count:
                key_failures.append(
                    f"{table} PK nulls={null_count}, duplicate keys={duplicate_count}"
                )

        for index in connection.execute(f"PRAGMA index_list({_quote(table)})").fetchall():
            if not index[2] or (len(index) > 4 and index[4]):
                continue
            index_columns = [
                row[2]
                for row in connection.execute(
                    f"PRAGMA index_info({_quote(index[1])})"
                ).fetchall()
            ]
            if not index_columns or any(column is None for column in index_columns):
                continue
            grouping = ", ".join(_quote(column) for column in index_columns)
            duplicate_count = connection.execute(
                f"SELECT count(*) FROM (SELECT 1 FROM {_quote(table)} "
                f"GROUP BY {grouping} HAVING count(*) > 1)"
            ).fetchone()[0]
            if duplicate_count:
                key_failures.append(
                    f"{table}.{index[1]} has {duplicate_count} duplicate key groups"
                )
    report.add(
        "primary and unique keys",
        not key_failures,
        "; ".join(key_failures) if key_failures else "no null or duplicate primary/unique keys",
    )
    return actual_counts


def _check_row_requirements(
    connection: sqlite3.Connection,
    report: DatasetReport,
    manifest: dict[str, Any],
) -> None:
    parameters = manifest.get("parameters", {})
    if not isinstance(parameters, dict):
        report.add("dataset parameters", False, "manifest.parameters must be an object")
        return
    try:
        employee_count = int(
            connection.execute("SELECT count(*) FROM employee").fetchone()[0]
        )
    except sqlite3.Error as error:
        report.add("employee count", False, f"cannot read employee table: {error}")
        return
    report.employee_count = employee_count
    stated_count = parameters.get("employee_count")
    stated_size = parameters.get("size")
    expected_by_size = {"starter": 200, "full": 3000}
    size_correct = (
        stated_size in expected_by_size
        and employee_count == expected_by_size[stated_size]
        and stated_count == employee_count
    )
    report.add(
        "dataset size",
        size_correct,
        (
            f"{stated_size}: {employee_count} employees"
            if size_correct
            else f"size={stated_size!r}, manifest employees={stated_count!r}, "
            f"database employees={employee_count}"
        ),
    )

    period_rows = connection.execute(
        "SELECT period_id, start_date, end_date FROM pay_period ORDER BY start_date"
    ).fetchall()
    periods_valid = len(period_rows) == 3
    previous: date | None = None
    for period_id, start_value, end_value in period_rows:
        match = re.fullmatch(r"PP-(\d{4})-(\d{2})", period_id)
        try:
            start = date.fromisoformat(start_value)
            end = date.fromisoformat(end_value)
        except (TypeError, ValueError):
            periods_valid = False
            continue
        if (
            match is None
            or not 1 <= int(match.group(2)) <= 12
            or start.day != 1
            or start.year != int(match.group(1))
            or start.month != int(match.group(2))
            or start.month != end.month
            or start.year != end.year
            or end.day != (date(start.year + (start.month == 12), start.month % 12 + 1, 1) - date.resolution).day
            or (previous is not None and (start.year, start.month) != (
                previous.year + (previous.month == 12), previous.month % 12 + 1
            ))
        ):
            periods_valid = False
        previous = start
    manifest_periods = parameters.get("pay_periods")
    periods_valid = periods_valid and manifest_periods == [
        row[0] for row in period_rows
    ]
    report.add(
        "pay periods",
        periods_valid,
        "three consecutive monthly periods match the manifest"
        if periods_valid
        else f"database periods={period_rows}; manifest periods={manifest_periods!r}",
    )

    groups = int(connection.execute("SELECT count(*) FROM pay_group").fetchone()[0])
    calendars = int(
        connection.execute(
            "SELECT count(*) FROM paygroup_period_calendar"
        ).fetchone()[0]
    )
    report.add(
        "pay groups and calendars",
        groups == 6 and calendars == 18,
        f"pay groups={groups}; calendar rows={calendars} (expected 6 and 18)",
    )
    distinct_calendars = int(
        connection.execute(
            """
            SELECT count(*)
            FROM (
                SELECT period_id
                FROM paygroup_period_calendar
                GROUP BY period_id
                HAVING count(DISTINCT cutoff_date) = 6
                   AND count(DISTINCT pay_date) = 6
            )
            """
        ).fetchone()[0]
    )
    report.add(
        "group-specific calendar dates",
        distinct_calendars == 3,
        f"{distinct_calendars} of 3 periods have distinct cutoff and pay dates for all six groups",
    )
    allowance_types = int(
        connection.execute("SELECT count(*) FROM allowance_type").fetchone()[0]
    )
    deduction_types = int(
        connection.execute("SELECT count(*) FROM deduction_type").fetchone()[0]
    )
    report.add(
        "source catalogs",
        allowance_types == 4 and deduction_types == 4,
        f"allowance types={allowance_types}; deduction types={deduction_types} (expected 4 each)",
    )

    hourly, salaried = connection.execute(
        "SELECT sum(employment_type = 'hourly'), sum(employment_type = 'salaried') "
        "FROM employee"
    ).fetchone()
    expected_hourly = int(round(employee_count * 0.30))
    mix_valid = hourly == expected_hourly and salaried == employee_count - expected_hourly
    report.add(
        "hourly/salaried mix",
        mix_valid,
        f"hourly={hourly}; salaried={salaried}; expected={expected_hourly}/"
        f"{employee_count - expected_hourly}",
    )

    transaction_count = sum(
        int(connection.execute(f"SELECT count(*) FROM {_quote(table)}").fetchone()[0])
        for table in ("time_entry", "allowance", "deduction")
    )
    report.transaction_count = transaction_count
    is_full = stated_size == "full"
    volume_valid = not is_full or 95000 <= transaction_count <= 105000
    report.add(
        "transaction volume",
        volume_valid,
        f"{transaction_count} time-entry, allowance, and deduction rows"
        + (" (expected 95,000 to 105,000 for full)" if is_full else ""),
    )
    target = parameters.get("transaction_record_target_full")
    target_valid = target == 100000
    report.add(
        "manifest transaction target",
        target_valid,
        f"manifest target={target!r}; blueprint target=100000 records",
    )


def _check_ids(connection: sqlite3.Connection, report: DatasetReport) -> None:
    failures: list[str] = []
    for entity, (table, column) in ID_TABLES.items():
        pattern = ID_PATTERNS[entity]
        for (value,) in connection.execute(
            f"SELECT {_quote(column)} FROM {_quote(table)} ORDER BY {_quote(column)}"
        ):
            match = pattern.fullmatch(value or "")
            if match is None:
                failures.append(f"{table}.{column} has invalid ID {value!r}")
                continue
            if entity == "time_entry":
                embedded_date = match.group(2)
                try:
                    date.fromisoformat(embedded_date)
                except ValueError:
                    failures.append(f"time_entry has invalid date in ID {value!r}")
            elif entity == "payroll_input":
                month = int(match.group(3))
                if not 1 <= month <= 12:
                    failures.append(f"payroll_input has invalid month in ID {value!r}")
            elif entity == "pay_period":
                if not 1 <= int(value[-2:]) <= 12:
                    failures.append(f"pay_period has invalid month in ID {value!r}")
    report.add(
        "required ID formats",
        not failures,
        "; ".join(failures[:20]) if failures else "all populated identifier columns match required formats",
    )

    relationship_failures: list[str] = []
    checks = (
        (
            "time-entry ID/entity consistency",
            """
            SELECT count(*) FROM time_entry
            WHERE substr(time_entry_id, 6, 10) != employee_id
               OR substr(time_entry_id, 17, 10) != work_date
            """,
        ),
        (
            "payroll-input ID/entity consistency",
            """
            SELECT count(*)
            FROM payroll_input AS input
            JOIN pay_period AS period USING (period_id)
            WHERE substr(input.payroll_input_id, 5, 10) != input.employee_id
               OR substr(input.payroll_input_id, 16, 7) != substr(period.start_date, 1, 7)
            """,
        ),
        (
            "time-entry period membership",
            """
            SELECT count(*) FROM time_entry
            JOIN pay_period USING (period_id)
            WHERE work_date < pay_period.start_date OR work_date > pay_period.end_date
            """,
        ),
        (
            "payroll-export year consistency",
            """
            SELECT count(*) FROM payroll_export
            JOIN pay_period USING (period_id)
            WHERE substr(export_id, 5, 4) != substr(start_date, 1, 4)
            """,
        ),
    )
    for name, sql in checks:
        invalid = int(connection.execute(sql).fetchone()[0])
        if invalid:
            relationship_failures.append(f"{name}: {invalid} invalid rows")
    report.add(
        "identifier/entity relationships",
        not relationship_failures,
        "; ".join(relationship_failures) if relationship_failures else "IDs agree with their employee, date, and period",
    )


def _check_dates(connection: sqlite3.Connection, report: DatasetReport) -> None:
    failures: list[str] = []
    for table, columns in DATE_COLUMNS.items():
        for column in columns:
            invalid = int(
                connection.execute(
                    f"SELECT count(*) FROM {_quote(table)} "
                    f"WHERE {_quote(column)} IS NOT NULL AND "
                    f"(date({_quote(column)}) IS NULL OR date({_quote(column)}) != {_quote(column)})"
                ).fetchone()[0]
            )
            if invalid:
                failures.append(f"{table}.{column}: {invalid} invalid ISO dates")
    for table, columns in DATETIME_COLUMNS.items():
        for column in columns:
            invalid = int(
                connection.execute(
                    f"SELECT count(*) FROM {_quote(table)} "
                    f"WHERE {_quote(column)} IS NOT NULL AND datetime({_quote(column)}) IS NULL"
                ).fetchone()[0]
            )
            if invalid:
                failures.append(f"{table}.{column}: {invalid} invalid timestamps")
    report.add(
        "ISO dates and timestamps",
        not failures,
        "; ".join(failures) if failures else "all populated date and timestamp fields are valid",
    )


def _check_enums(connection: sqlite3.Connection, report: DatasetReport) -> None:
    failures: list[str] = []
    enum_specs = (
        ("employee", "employment_type", ("hourly", "salaried")),
        ("employee", "status", ("active", "inactive", "terminated")),
        ("time_entry", "status", ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")),
        ("payroll_input", "status", ("AGGREGATED", "VALIDATED", "BLOCKED", "APPROVED", "EXPORTED")),
        ("payroll_export", "status", ("CREATED", "RELEASED")),
        ("approval", "decision", ("APPROVED", "REJECTED", "WAIVED")),
        ("exception", "status", ("OPEN", "ACKNOWLEDGED", "RESOLVED", "WAIVED", "SUPERSEDED")),
    )
    for table, column, values in enum_specs:
        placeholders = ", ".join("?" for _ in values)
        invalid = int(
            connection.execute(
                f"SELECT count(*) FROM {_quote(table)} "
                f"WHERE {_quote(column)} NOT IN ({placeholders})",
                values,
            ).fetchone()[0]
        )
        if invalid:
            failures.append(f"{table}.{column}: {invalid} values outside schema CHECK")
    invalid_source_types = int(
        connection.execute(
            """
            SELECT count(*) FROM payroll_input_source
            WHERE source_type NOT IN ('time_entry', 'leave_record', 'allowance', 'deduction')
            """
        ).fetchone()[0]
    )
    if invalid_source_types:
        failures.append(
            f"payroll_input_source.source_type: {invalid_source_types} values outside schema CHECK"
        )
    report.add(
        "schema-defined lifecycle enums",
        not failures,
        "; ".join(failures) if failures else "all populated enum fields match schema CHECK values",
    )


def _check_money_and_arithmetic(
    connection: sqlite3.Connection,
    report: DatasetReport,
) -> None:
    money_columns = (
        ("employee", "base_rate_minor"),
        ("allowance_type", "default_amount_minor"),
        ("deduction_type", "default_amount_minor"),
        ("allowance", "amount_minor"),
        ("deduction", "amount_minor"),
        ("payroll_input", "gross_minor"),
        ("payroll_input", "deductions_minor"),
        ("payroll_input", "net_minor"),
        ("payroll_export", "total_net_minor"),
        ("payroll_export_line", "amount_minor"),
    )
    noninteger: list[str] = []
    for table, column in money_columns:
        invalid = int(
            connection.execute(
                f"SELECT count(*) FROM {_quote(table)} "
                f"WHERE {_quote(column)} IS NOT NULL AND typeof({_quote(column)}) != 'integer'"
            ).fetchone()[0]
        )
        if invalid:
            noninteger.append(f"{table}.{column}: {invalid} non-integer values")
    report.add(
        "integer minor-unit money",
        not noninteger,
        "; ".join(noninteger) if noninteger else "all populated money columns use SQLite INTEGER values",
    )

    invalid_net = int(
        connection.execute(
            "SELECT count(*) FROM payroll_input "
            "WHERE net_minor != gross_minor - deductions_minor"
        ).fetchone()[0]
    )
    report.add(
        "payroll net arithmetic",
        invalid_net == 0,
        f"{invalid_net} inputs violate net = gross - deductions",
    )

    mismatches = connection.execute(
        """
        WITH
        time_totals AS (
            SELECT employee_id, period_id,
                   SUM(CASE WHEN entry_type = 'REGULAR' THEN MIN(hours, 8.0) ELSE 0 END) AS regular_hours,
                   SUM(CASE
                       WHEN entry_type = 'REGULAR' THEN MAX(hours - 8.0, 0)
                       WHEN entry_type = 'OVERTIME' THEN hours
                       ELSE 0
                   END) AS ot_hours
            FROM time_entry
            WHERE status = 'APPROVED'
            GROUP BY employee_id, period_id
        ),
        allowance_totals AS (
            SELECT employee_id, period_id, SUM(amount_minor) AS amount_minor
            FROM allowance WHERE status = 'APPROVED'
            GROUP BY employee_id, period_id
        ),
        leave_deduction_totals AS (
            SELECT employee_id, period_id, SUM(amount_minor) AS amount_minor
            FROM deduction WHERE status = 'APPROVED' AND source_leave_id IS NOT NULL
            GROUP BY employee_id, period_id
        ),
        deduction_totals AS (
            SELECT employee_id, period_id, SUM(amount_minor) AS amount_minor
            FROM deduction WHERE status = 'APPROVED' AND source_leave_id IS NULL
            GROUP BY employee_id, period_id
        ),
        expected AS (
            SELECT input.payroll_input_id,
                   COALESCE(time_totals.regular_hours, 0) AS regular_hours,
                   COALESCE(time_totals.ot_hours, 0) AS ot_hours,
                   CASE WHEN employee.employment_type = 'hourly' THEN
                       COALESCE(time_totals.regular_hours, 0) * employee.base_rate_minor
                       + COALESCE(time_totals.ot_hours, 0) * employee.base_rate_minor * pay_group.ot_multiplier
                   ELSE employee.base_rate_minor
                       + COALESCE(time_totals.ot_hours, 0) * employee.base_rate_minor / 160.0 * pay_group.ot_multiplier
                   END
                   + COALESCE(allowance_totals.amount_minor, 0)
                   - COALESCE(leave_deduction_totals.amount_minor, 0) AS gross_amount,
                   COALESCE(deduction_totals.amount_minor, 0) AS deductions_amount
            FROM payroll_input AS input
            JOIN employee USING (employee_id)
            JOIN pay_group USING (pay_group_id)
            LEFT JOIN time_totals USING (employee_id, period_id)
            LEFT JOIN allowance_totals USING (employee_id, period_id)
            LEFT JOIN leave_deduction_totals USING (employee_id, period_id)
            LEFT JOIN deduction_totals USING (employee_id, period_id)
        )
        SELECT count(*)
        FROM payroll_input AS input
        JOIN expected USING (payroll_input_id)
        WHERE abs(input.regular_hours - expected.regular_hours) > 0.000001
           OR abs(input.ot_hours - expected.ot_hours) > 0.000001
           OR input.gross_minor != CAST(ROUND(expected.gross_amount) AS INTEGER)
           OR input.deductions_minor != CAST(ROUND(expected.deductions_amount) AS INTEGER)
           OR input.net_minor != CAST(ROUND(expected.gross_amount - expected.deductions_amount) AS INTEGER)
        """
    ).fetchone()[0]
    report.add(
        "payroll source aggregation",
        mismatches == 0,
        f"{mismatches} payroll inputs differ from approved-source SQL aggregation",
    )

    export_mismatches = int(
        connection.execute(
            """
            SELECT count(*)
            FROM payroll_export AS export
            WHERE export.line_count != (
                    SELECT count(*) FROM payroll_export_line
                    WHERE export_id = export.export_id
                )
               OR export.total_net_minor != (
                    SELECT COALESCE(sum(amount_minor), 0)
                    FROM payroll_export_line
                    WHERE export_id = export.export_id
                )
            """
        ).fetchone()[0]
    )
    invalid_export_links = int(
        connection.execute(
            """
            SELECT count(*)
            FROM payroll_export_line AS line
            JOIN payroll_export AS export USING (export_id)
            JOIN payroll_input AS input USING (payroll_input_id)
            JOIN employee USING (employee_id)
            WHERE input.period_id != export.period_id
               OR employee.pay_group_id != export.pay_group_id
            """
        ).fetchone()[0]
    )
    report.add(
        "payroll export totals and scope",
        export_mismatches == 0 and invalid_export_links == 0,
        f"incorrect export totals={export_mismatches}; out-of-scope lines={invalid_export_links}",
    )
    uncovered_inputs = len(
        connection.execute(
            """
            SELECT count(*)
            FROM payroll_input AS input
            LEFT JOIN payroll_export_line AS line
              ON line.payroll_input_id = input.payroll_input_id
            GROUP BY input.payroll_input_id
            HAVING count(line.payroll_input_id) != 1
            """
        ).fetchall()
    )
    export_key_duplicates = int(
        connection.execute(
            """
            SELECT count(*) FROM (
                SELECT pay_group_id, period_id
                FROM payroll_export
                GROUP BY pay_group_id, period_id
                HAVING count(*) != 1
            )
            """
        ).fetchone()[0]
    )
    export_count = int(
        connection.execute("SELECT count(*) FROM payroll_export").fetchone()[0]
    )
    unreleased_exports = int(
        connection.execute(
            "SELECT count(*) FROM payroll_export WHERE status != 'RELEASED'"
        ).fetchone()[0]
    )
    report.add(
        "baseline export coverage",
        uncovered_inputs == 0
        and export_key_duplicates == 0
        and export_count == 18
        and unreleased_exports == 0,
        f"inputs without exactly one export line={uncovered_inputs}; "
        f"duplicate group-period exports={export_key_duplicates}; "
        f"export rows={export_count}; not released={unreleased_exports}",
    )


def _check_source_links(connection: sqlite3.Connection, report: DatasetReport) -> None:
    source_specs = {
        "time_entry": ("time_entry", "time_entry_id"),
        "leave_record": ("leave_record", "leave_id"),
        "allowance": ("allowance", "allowance_id"),
        "deduction": ("deduction", "deduction_id"),
    }
    failures: list[str] = []
    for source_type, (table, identifier) in source_specs.items():
        invalid = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM payroll_input_source AS source
                JOIN payroll_input AS input USING (payroll_input_id)
                LEFT JOIN {_quote(table)} AS record
                  ON record.{_quote(identifier)} = source.source_id
                 AND record.employee_id = input.employee_id
                 AND record.period_id = input.period_id
                WHERE source.source_type = ?
                  AND record.{_quote(identifier)} IS NULL
                """,
                (source_type,),
            ).fetchone()[0]
        )
        if invalid:
            failures.append(f"{source_type}: {invalid} missing or mismatched links")
        missing_approved = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {_quote(table)} AS record
                LEFT JOIN payroll_input AS input
                  ON input.employee_id = record.employee_id
                 AND input.period_id = record.period_id
                LEFT JOIN payroll_input_source AS source
                  ON source.payroll_input_id = input.payroll_input_id
                 AND source.source_type = ?
                 AND source.source_id = record.{_quote(identifier)}
                WHERE record.status = 'APPROVED'
                  AND source.payroll_input_id IS NULL
                """,
                (source_type,),
            ).fetchone()[0]
        )
        if missing_approved:
            failures.append(
                f"{source_type}: {missing_approved} approved records lack a payroll input source link"
            )
    unpaid_leave_without_deduction = int(
        connection.execute(
            """
            SELECT count(*)
            FROM leave_record AS leave
            LEFT JOIN deduction
              ON deduction.source_leave_id = leave.leave_id
             AND deduction.employee_id = leave.employee_id
             AND deduction.period_id = leave.period_id
             AND deduction.status = 'APPROVED'
            WHERE leave.status = 'APPROVED' AND leave.paid_flag = 0
              AND deduction.deduction_id IS NULL
            """
        ).fetchone()[0]
    )
    if unpaid_leave_without_deduction:
        failures.append(
            f"{unpaid_leave_without_deduction} approved unpaid leaves lack a linked deduction"
        )
    report.add(
        "payroll input source traceability",
        not failures,
        "; ".join(failures) if failures else "source IDs exist and agree with linked employee-period inputs",
    )


def _check_lifecycle_history(connection: sqlite3.Connection, report: DatasetReport) -> None:
    allowed = {
        "time_entry": {
            (None, "DRAFT"),
            ("DRAFT", "SUBMITTED"),
            ("SUBMITTED", "APPROVED"),
            ("SUBMITTED", "REJECTED"),
            ("APPROVED", "SUPERSEDED"),
        },
        "payroll_input": {
            ("AGGREGATED", "VALIDATED"),
            ("AGGREGATED", "BLOCKED"),
            ("VALIDATED", "APPROVED"),
            ("VALIDATED", "BLOCKED"),
            ("APPROVED", "EXPORTED"),
        },
        "payroll_export": {(None, "CREATED"), ("CREATED", "RELEASED")},
    }
    specs = (
        ("time_entry", "time_entry_id", "status"),
        ("payroll_input", "payroll_input_id", "status"),
        ("payroll_export", "export_id", "status"),
    )
    failures: list[str] = []
    for entity_type, table_id, status_column in specs:
        current_rows = connection.execute(
            f"SELECT {_quote(table_id)}, {_quote(status_column)} "
            f"FROM {_quote(entity_type)} ORDER BY {_quote(table_id)}"
        ).fetchall()
        for entity_id, current_status in current_rows:
            events = connection.execute(
                """
                SELECT from_state, to_state FROM state_event
                WHERE entity_type = ? AND entity_id = ?
                ORDER BY event_id
                """,
                (entity_type, entity_id),
            ).fetchall()
            if not events:
                failures.append(f"{entity_type} {entity_id} has no state history")
                continue
            previous: str | None = None
            for index, (from_state, to_state) in enumerate(events):
                if (from_state, to_state) not in allowed[entity_type]:
                    failures.append(
                        f"{entity_type} {entity_id} has invalid transition "
                        f"{from_state!r}->{to_state!r}"
                    )
                    break
                if index == 0:
                    initial_states = {
                        "time_entry": None,
                        "payroll_input": "AGGREGATED",
                        "payroll_export": None,
                    }
                    initial_state = initial_states[entity_type]
                    if from_state != initial_state:
                        failures.append(
                            f"{entity_type} {entity_id} history has invalid initial state {from_state!r}"
                        )
                        break
                elif from_state != previous:
                    failures.append(f"{entity_type} {entity_id} history is discontinuous")
                    break
                previous = to_state
            if previous != current_status:
                failures.append(
                    f"{entity_type} {entity_id} ends at {previous!r}, "
                    f"but current status is {current_status!r}"
                )
    report.add(
        "lifecycle history",
        not failures,
        "; ".join(failures[:20]) if failures else "time entries, payroll inputs, and exports have valid state histories",
    )


def _scenario_is_valid(
    connection: sqlite3.Connection,
    label: dict[str, str],
) -> bool:
    issue = label["issue_type"]
    employee_id = label["employee_id"]
    period_id = label["period_id"]
    entity_id = label["entity_id"]
    if issue in ("hours_exceed_period_max", "boundary_exact_max_hours"):
        total, maximum = connection.execute(
            """
            SELECT COALESCE(sum(time_entry.hours), 0), pay_group.max_hours_per_period
            FROM time_entry
            JOIN employee USING (employee_id)
            JOIN pay_group USING (pay_group_id)
            JOIN payroll_input AS input
              ON input.employee_id = time_entry.employee_id
             AND input.period_id = time_entry.period_id
            WHERE time_entry.employee_id = ? AND time_entry.period_id = ?
              AND input.payroll_input_id = ?
              AND time_entry.entry_type = 'REGULAR'
              AND time_entry.status = 'APPROVED'
            """,
            (employee_id, period_id, entity_id),
        ).fetchone()
        return total > maximum if issue == "hours_exceed_period_max" else math.isclose(total, maximum, abs_tol=0.01)
    if issue == "duplicate_allowance":
        return connection.execute(
            """
            SELECT count(*) FROM allowance AS target
            JOIN allowance AS duplicate
              ON duplicate.employee_id = target.employee_id
             AND duplicate.period_id = target.period_id
             AND duplicate.allowance_type_id = target.allowance_type_id
             AND duplicate.amount_minor = target.amount_minor
             AND duplicate.allowance_id != target.allowance_id
            WHERE target.allowance_id = ? AND target.employee_id = ?
              AND target.period_id = ? AND target.status = 'APPROVED'
              AND duplicate.status = 'APPROVED'
            """,
            (entity_id, employee_id, period_id),
        ).fetchone()[0] > 0
    if issue == "leave_deduction_applied_twice":
        return connection.execute(
            """
            SELECT count(*) FROM deduction AS target
            JOIN deduction AS duplicate
              ON duplicate.source_leave_id = target.source_leave_id
             AND duplicate.deduction_id != target.deduction_id
             AND duplicate.status = 'APPROVED'
            WHERE target.deduction_id = ? AND target.employee_id = ?
              AND target.period_id = ? AND target.source_leave_id IS NOT NULL
              AND target.status = 'APPROVED'
            """,
            (entity_id, employee_id, period_id),
        ).fetchone()[0] > 0
    if issue == "unapproved_time_exported":
        return connection.execute(
            """
            SELECT count(*)
            FROM time_entry AS entry
            JOIN payroll_input_source AS source
              ON source.source_type = 'time_entry'
             AND source.source_id = entry.time_entry_id
            JOIN payroll_export_line AS line
              ON line.payroll_input_id = source.payroll_input_id
            WHERE entry.time_entry_id = ? AND entry.employee_id = ?
              AND entry.period_id = ? AND entry.status = 'SUBMITTED'
            """,
            (entity_id, employee_id, period_id),
        ).fetchone()[0] > 0
    if issue == "totals_fail_to_reconcile":
        try:
            export_id, input_id = entity_id.split(":", 1)
        except ValueError:
            return False
        return connection.execute(
            """
            SELECT count(*) FROM payroll_export_line AS line
            JOIN payroll_input AS input USING (payroll_input_id)
            WHERE line.export_id = ? AND line.payroll_input_id = ?
              AND input.employee_id = ? AND input.period_id = ?
              AND line.amount_minor != input.net_minor
            """,
            (export_id, input_id, employee_id, period_id),
        ).fetchone()[0] == 1
    if issue == "missing_bank":
        return connection.execute(
            "SELECT count(*) FROM employee WHERE employee_id = ? "
            "AND bank_account IS NULL AND bank_routing IS NULL",
            (employee_id,),
        ).fetchone()[0] == 1
    if issue == "missing_tax":
        return connection.execute(
            "SELECT count(*) FROM employee WHERE employee_id = ? AND tax_id IS NULL",
            (employee_id,),
        ).fetchone()[0] == 1
    if issue == "duplicate_hours":
        return connection.execute(
            """
            SELECT count(*)
            FROM time_entry AS target
            JOIN time_entry AS duplicate
              ON duplicate.employee_id = target.employee_id
             AND duplicate.period_id = target.period_id
             AND duplicate.work_date = target.work_date
             AND duplicate.entry_type = target.entry_type
             AND duplicate.time_entry_id != target.time_entry_id
             AND duplicate.supersedes_id IS NULL
            WHERE target.time_entry_id = ? AND target.employee_id = ?
              AND target.period_id = ? AND target.status = 'APPROVED'
              AND target.entry_type = 'REGULAR'
              AND duplicate.status = 'APPROVED'
              AND target.supersedes_id IS NULL
            """,
            (entity_id, employee_id, period_id),
        ).fetchone()[0] > 0
    if issue == "outlier_hours":
        return connection.execute(
            """
            SELECT count(*) FROM time_entry
            JOIN employee USING (employee_id)
            JOIN pay_group USING (pay_group_id)
            WHERE time_entry_id = ?
              AND hours >= max_hours_per_day * 1.5
              AND employee_id = ? AND period_id = ?
            """,
            (entity_id, employee_id, period_id),
        ).fetchone()[0] == 1
    if issue == "boundary_legitimate_correction":
        row = connection.execute(
            """
            SELECT revision.status, revision.submission_seq, original.status,
                   revision.employee_id, revision.period_id
            FROM time_entry AS revision
            JOIN time_entry AS original
              ON original.time_entry_id = revision.supersedes_id
            WHERE revision.time_entry_id = ?
            """,
            (entity_id,),
        ).fetchone()
        return (
            row is not None
            and row[0] == "APPROVED"
            and row[1] == 2
            and row[2] == "SUPERSEDED"
            and row[3] == employee_id
            and row[4] == period_id
            and entity_id.endswith("-R1")
        )
    if issue == "boundary_legitimate_resubmission":
        row = connection.execute(
            """
            SELECT revision.status, revision.submission_seq, original.status,
                   revision.employee_id, revision.period_id
            FROM time_entry AS revision
            JOIN time_entry AS original
              ON original.time_entry_id = revision.supersedes_id
            WHERE revision.time_entry_id = ?
            """,
            (entity_id,),
        ).fetchone()
        return (
            row is not None
            and row[0] == "APPROVED"
            and row[1] == 2
            and row[2] == "REJECTED"
            and row[3] == employee_id
            and row[4] == period_id
            and entity_id.endswith("-R2")
        )
    return False


def _label_entity_exists(
    connection: sqlite3.Connection,
    label: dict[str, str],
) -> bool:
    references = {
        "payroll_input": ("payroll_input", "payroll_input_id"),
        "allowance": ("allowance", "allowance_id"),
        "time_entry": ("time_entry", "time_entry_id"),
        "deduction": ("deduction", "deduction_id"),
        "employee": ("employee", "employee_id"),
    }
    entity_type = label["entity_type"]
    entity_id = label["entity_id"]
    if entity_type == "payroll_export_line":
        try:
            export_id, payroll_input_id = entity_id.split(":", 1)
        except ValueError:
            return False
        return connection.execute(
            "SELECT count(*) FROM payroll_export_line "
            "WHERE export_id = ? AND payroll_input_id = ?",
            (export_id, payroll_input_id),
        ).fetchone()[0] == 1
    reference = references.get(entity_type)
    if reference is None:
        return False
    table, identifier = reference
    return connection.execute(
        f"SELECT count(*) FROM {_quote(table)} WHERE {_quote(identifier)} = ?",
        (entity_id,),
    ).fetchone()[0] == 1


def _check_planted_duplicate_coverage(
    connection: sqlite3.Connection,
    report: DatasetReport,
    labels: list[dict[str, str]],
) -> None:
    expected_ids = {
        issue: {row["entity_id"] for row in labels if row["issue_type"] == issue}
        for issue in ("duplicate_allowance", "leave_deduction_applied_twice", "duplicate_hours")
    }
    queries = {
        "duplicate_allowance": """
            WITH ranked AS (
                SELECT allowance_id,
                       row_number() OVER (
                           PARTITION BY employee_id, period_id, allowance_type_id
                           ORDER BY allowance_id
                       ) AS duplicate_number
                FROM allowance
                WHERE status = 'APPROVED'
            )
            SELECT allowance_id FROM ranked WHERE duplicate_number > 1
        """,
        "leave_deduction_applied_twice": """
            WITH ranked AS (
                SELECT deduction_id,
                       row_number() OVER (
                           PARTITION BY source_leave_id
                           ORDER BY deduction_id
                       ) AS duplicate_number
                FROM deduction
                WHERE source_leave_id IS NOT NULL AND status = 'APPROVED'
            )
            SELECT deduction_id FROM ranked WHERE duplicate_number > 1
        """,
        "duplicate_hours": """
            WITH ranked AS (
                SELECT time_entry_id,
                       row_number() OVER (
                           PARTITION BY employee_id, period_id, work_date, entry_type
                           ORDER BY time_entry_id
                       ) AS duplicate_number
                FROM time_entry
                WHERE status = 'APPROVED'
                  AND entry_type = 'REGULAR'
                  AND supersedes_id IS NULL
            )
            SELECT time_entry_id FROM ranked WHERE duplicate_number > 1
        """,
    }
    failures: list[str] = []
    for issue, sql in queries.items():
        database_ids = {row[0] for row in connection.execute(sql).fetchall()}
        labelled_ids = expected_ids[issue]
        if database_ids != labelled_ids:
            unlabelled = sorted(database_ids - labelled_ids)
            missing = sorted(labelled_ids - database_ids)
            failures.append(
                f"{issue}: unlabelled duplicates={unlabelled[:10]}, "
                f"labels without duplicate rows={missing[:10]}"
            )
    report.add(
        "duplicate anomaly coverage",
        not failures,
        "; ".join(failures) if failures else "all duplicate allowances, leave deductions, and hours are labelled",
    )


def _check_ground_truth(
    connection: sqlite3.Connection,
    report: DatasetReport,
    labels_path: Path | None,
    manifest: dict[str, Any],
) -> None:
    if labels_path is None:
        report.add("ground-truth labels", False, "manifest does not identify ground_truth/labels.csv")
        return
    try:
        with labels_path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            labels = list(reader)
            headers = reader.fieldnames
    except (OSError, UnicodeError, csv.Error) as error:
        report.add("ground-truth labels", False, f"cannot read labels: {error}")
        return
    report.label_count = len(labels)
    if headers != list(GROUND_TRUTH_COLUMNS):
        report.add(
            "ground-truth columns",
            False,
            f"expected {list(GROUND_TRUTH_COLUMNS)}, found {headers}",
        )
    else:
        report.add("ground-truth columns", True, f"all {len(headers)} required columns are present and ordered")

    labels_well_formed = True
    scenario_failures: list[str] = []
    issue_counts: Counter[str] = Counter()
    gt_ids: set[str] = set()
    known_employees = {
        row[0] for row in connection.execute("SELECT employee_id FROM employee")
    }
    known_periods = {
        row[0] for row in connection.execute("SELECT period_id FROM pay_period")
    }
    for row_number, label in enumerate(labels, start=1):
        issue = label.get("issue_type", "")
        issue_counts[issue] += 1
        expected = ISSUE_RULES.get(issue)
        gt_id = label.get("gt_id", "")
        if (
            expected is None
            or (label.get("expected_rule_id"), label.get("severity"), label.get("expected_decision"))
            != expected
            or label.get("entity_type") != ISSUE_ENTITY_TYPES.get(issue)
            or not re.fullmatch(r"GT-\d{6,}", gt_id)
            or gt_id in gt_ids
            or not label.get("employee_id")
            or not label.get("period_id")
            or label.get("employee_id") not in known_employees
            or label.get("period_id") not in known_periods
            or (
                label.get("entity_type") == "employee"
                and label.get("entity_id") != label.get("employee_id")
            )
            or not label.get("injected_by")
            or not label.get("description")
        ):
            labels_well_formed = False
        gt_ids.add(gt_id)
        if expected is not None and (
            not _label_entity_exists(connection, label)
            or not _scenario_is_valid(connection, label)
        ):
            scenario_failures.append(f"row {row_number} ({issue}, {label.get('entity_id')})")
    sequential_ids = [f"GT-{number:06d}" for number in range(1, len(labels) + 1)]
    if [row.get("gt_id") for row in labels] != sequential_ids:
        labels_well_formed = False

    parameters = manifest.get("parameters", {})
    anomaly_plan = (
        parameters.get("anomaly_plan_full_scale", {})
        if isinstance(parameters, dict)
        else {}
    )
    employee_count = report.employee_count or 0
    count_mismatches = []
    if not isinstance(anomaly_plan, dict):
        anomaly_plan = {}
        count_mismatches.append("manifest anomaly plan must be an object")
    for issue, base_count in anomaly_plan.items():
        if not isinstance(base_count, int) or base_count < 0:
            count_mismatches.append(f"invalid anomaly-plan count for {issue}")
            continue
        expected_count = (
            0
            if base_count == 0
            else max(1, int(round(base_count * employee_count / 3000)))
        )
        if issue in ("boundary_legitimate_correction", "boundary_legitimate_resubmission"):
            expected_count = int(round(base_count * employee_count / 3000))
        if issue_counts[issue] != expected_count:
            count_mismatches.append(
                f"{issue}: expected {expected_count}, found {issue_counts[issue]}"
            )
    if employee_count == 3000:
        for issue, required_count in REQUIRED_FULL_ANOMALY_COUNTS.items():
            if anomaly_plan.get(issue) != required_count:
                count_mismatches.append(
                    f"{issue}: full-scale plan must be {required_count}, "
                    f"found {anomaly_plan.get(issue)!r}"
                )
    for issue in ISSUE_RULES:
        if issue not in anomaly_plan and issue_counts[issue]:
            count_mismatches.append(f"{issue}: labels exist but no anomaly-plan entry")

    report.add(
        "ground-truth labels and planned counts",
        labels_well_formed and not count_mismatches,
        (
            f"{len(labels)} labels, {len(issue_counts)} issue types; "
            + ("; ".join(count_mismatches) if count_mismatches else "IDs, rule labels, decisions, severities, and counts match")
        ),
    )
    report.add(
        "anomaly and boundary scenarios",
        not scenario_failures,
        (
            "; ".join(scenario_failures[:20])
            if scenario_failures
            else f"all {len(labels)} labelled scenarios exist in the database with the expected condition"
        ),
    )
    _check_planted_duplicate_coverage(connection, report, labels)
    labelled_missing_bank = {
        row["employee_id"] for row in labels if row["issue_type"] == "missing_bank"
    }
    labelled_missing_tax = {
        row["employee_id"] for row in labels if row["issue_type"] == "missing_tax"
    }
    actual_missing_bank = {
        row[0]
        for row in connection.execute(
            "SELECT employee_id FROM employee "
            "WHERE bank_account IS NULL OR bank_routing IS NULL"
        )
    }
    actual_missing_tax = {
        row[0]
        for row in connection.execute(
            "SELECT employee_id FROM employee WHERE tax_id IS NULL"
        )
    }
    missing_details_match = (
        actual_missing_bank == labelled_missing_bank
        and actual_missing_tax == labelled_missing_tax
    )
    report.add(
        "planned missing employee details",
        missing_details_match,
        (
            "all missing bank and tax details are exactly the labelled anomalies"
            if missing_details_match
            else f"unlabelled/missing bank labels={sorted(actual_missing_bank ^ labelled_missing_bank)}; "
            f"unlabelled/missing tax labels={sorted(actual_missing_tax ^ labelled_missing_tax)}"
        ),
    )
    ground_truth_tables = int(
        connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'ground_truth'"
        ).fetchone()[0]
    )
    report.add(
        "ground-truth database separation",
        ground_truth_tables == 0,
        "no ground_truth table exists in the operational database"
        if ground_truth_tables == 0
        else "ground_truth table found in operational database",
    )


def validate_dataset(
    dataset_path: str | Path,
    *,
    expected_size: str | None = None,
) -> DatasetReport:
    """Run Module 4 integrity, provenance, arithmetic, and label checks."""
    dataset_root, database_path = _resolve_dataset_path(dataset_path)
    report = DatasetReport(dataset_path=dataset_root)
    manifest_path = dataset_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        report.add("manifest file", False, f"cannot read {manifest_path}: {error}")
        return report
    if not isinstance(manifest, dict):
        report.add("manifest format", False, "manifest must contain a JSON object")
        return report
    report.add("manifest file", True, f"read {manifest_path}")
    report.seed = manifest.get("seed") if isinstance(manifest.get("seed"), int) else None
    if report.seed is None or report.seed < 0:
        report.add("manifest seed", False, f"invalid seed {manifest.get('seed')!r}")
    else:
        report.add("manifest seed", True, f"seed {report.seed}")

    parameters = manifest.get("parameters", {})
    manifest_size = parameters.get("size") if isinstance(parameters, dict) else None
    if expected_size is not None and manifest_size != expected_size:
        report.add(
            "requested dataset size",
            False,
            f"requested {expected_size}, manifest identifies {manifest_size!r}",
        )
    labels_path = _manifest_check(report, dataset_root, manifest, database_path)
    if not database_path.is_file():
        report.add("database file", False, f"database not found: {database_path}")
        return report
    report.add("database file", True, f"found {database_path}")
    try:
        connection = get_connection(database_path)
    except sqlite3.Error as error:
        report.add("database connection", False, f"cannot open SQLite database: {error}")
        return report
    try:
        actual_counts = _check_table_and_key_integrity(connection, report)
        _check_manifest_row_counts(report, manifest, actual_counts)
        _check_row_requirements(connection, report, manifest)
        _check_ids(connection, report)
        _check_dates(connection, report)
        _check_enums(connection, report)
        _check_money_and_arithmetic(connection, report)
        _check_source_links(connection, report)
        _check_lifecycle_history(connection, report)
        _check_ground_truth(connection, report, labels_path, manifest)
    except sqlite3.Error as error:
        report.add("database verification", False, f"SQLite validation query failed: {error}")
    finally:
        connection.close()
    return report


def verify_reproducibility(
    *,
    seed: int = 20261022,
    employee_count: int = 200,
) -> ReproducibilityReport:
    """Generate twice in isolated temporary directories and compare checksums."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if (
        isinstance(employee_count, bool)
        or not isinstance(employee_count, int)
        or employee_count < 1
    ):
        raise ValueError("employee_count must be a positive integer")
    config = load_config(environment={})
    config = type(config)(
        seed=seed,
        employee_count=employee_count,
        pay_periods=config.pay_periods,
        database_path=config.database_path,
        ground_truth_dir=config.ground_truth_dir,
        anomaly_plan=config.anomaly_plan,
    )
    with tempfile.TemporaryDirectory(prefix="paygate-repro-") as temporary_directory:
        root = Path(temporary_directory)
        first: GenerationSummary = generate_dataset(
            config=config,
            employee_count=employee_count,
            output_dir=root / "first",
        )
        second: GenerationSummary = generate_dataset(
            config=config,
            employee_count=employee_count,
            output_dir=root / "second",
        )
    passed = first.checksums == second.checksums
    detail = (
        f"{len(first.checksums)} checksums are identical across two independent runs"
        if passed
        else "independent generation checksums differ"
    )
    return ReproducibilityReport(
        seed=seed,
        employee_count=employee_count,
        checksums=first.checksums,
        passed=passed,
        detail=detail,
    )
