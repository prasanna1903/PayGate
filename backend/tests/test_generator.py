"""Tests for deterministic PayGate synthetic data generation."""

import csv
import json
from pathlib import Path

from backend.db.connection import get_connection
from backend.generator.config import load_config
from backend.generator.generate import generate_dataset


GENERATED_TABLES = (
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
    "approval",
    "payroll_export",
    "payroll_export_line",
    "state_event",
)


def _rows(database_path: Path, table: str) -> list[tuple[object, ...]]:
    connection = get_connection(database_path)
    try:
        return connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
    finally:
        connection.close()


def test_starter_generation_is_deterministic(tmp_path: Path) -> None:
    first_database = tmp_path / "first.db"
    second_database = tmp_path / "second.db"
    config = load_config(environment={})

    first_summary = generate_dataset(
        "starter", config=config, database_path=first_database
    )
    second_summary = generate_dataset(
        "starter", config=config, database_path=second_database
    )

    assert first_summary.table_counts == second_summary.table_counts
    assert first_summary.employee_count == 200
    assert first_summary.checksums[first_database.name] == second_summary.checksums[
        second_database.name
    ]
    assert first_summary.checksums[
        "ground_truth/first_labels.csv"
    ] == second_summary.checksums["ground_truth/second_labels.csv"]
    for table in GENERATED_TABLES:
        assert _rows(first_database, table) == _rows(second_database, table)
    assert first_summary.ground_truth_path.read_bytes() == (
        second_summary.ground_truth_path.read_bytes()
    )


def test_starter_generation_creates_three_periods_and_source_links(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "starter.db"
    summary = generate_dataset(
        "starter",
        config=load_config(environment={}),
        database_path=database_path,
    )
    connection = get_connection(database_path)
    try:
        assert summary.table_counts["employee"] == 200
        assert summary.table_counts["pay_period"] == 3
        assert summary.table_counts["paygroup_period_calendar"] == 18
        assert summary.table_counts["payroll_input"] == connection.execute(
            "SELECT count(*) FROM employee JOIN pay_period "
            "ON employee.effective_from <= pay_period.end_date"
        ).fetchone()[0]
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT count(*) FROM payroll_input_source"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT count(*) FROM payroll_export WHERE status = 'RELEASED'"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT count(*) FROM payroll_export_line"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT count(*) FROM payroll_input WHERE gross_minor - deductions_minor != net_minor"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM payroll_input_source "
            "GROUP BY payroll_input_id, source_type, source_id HAVING count(*) > 1"
        ).fetchall() == []
        assert connection.execute(
            "SELECT count(DISTINCT cutoff_date), count(DISTINCT pay_date) "
            "FROM paygroup_period_calendar WHERE period_id = 'PP-2026-01'"
        ).fetchone() == (6, 6)
        assert connection.execute(
            """
            SELECT count(*)
            FROM time_entry AS entry
            JOIN employee USING (employee_id)
            JOIN leave_record AS leave
              ON leave.employee_id = entry.employee_id
             AND leave.period_id = entry.period_id
            WHERE employee.employment_type = 'hourly'
              AND leave.status = 'APPROVED'
              AND entry.work_date BETWEEN leave.start_date AND leave.end_date
            """
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM time_entry JOIN employee USING (employee_id) "
            "WHERE (employee.employment_type = 'hourly' AND entry_type != 'REGULAR') "
            "OR (employee.employment_type = 'salaried' AND entry_type != 'OVERTIME')"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM time_entry WHERE time_entry_id LIKE '%-R1'"
        ).fetchone()[0] >= 1
        assert connection.execute(
            "SELECT count(*) FROM time_entry WHERE time_entry_id LIKE '%-R2'"
        ).fetchone()[0] >= 1
        assert connection.execute(
            """
            SELECT count(*)
            FROM time_entry AS revision
            JOIN time_entry AS original
              ON original.time_entry_id = revision.supersedes_id
            WHERE revision.submission_seq = 2
              AND original.status = 'SUPERSEDED'
            """
        ).fetchone()[0] >= 1
        assert connection.execute(
            """
            SELECT count(*)
            FROM time_entry AS revision
            JOIN time_entry AS original
              ON original.time_entry_id = revision.supersedes_id
            WHERE revision.submission_seq = 2
              AND original.status = 'REJECTED'
            """
        ).fetchone()[0] >= 1
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'ground_truth'"
        ).fetchone()[0] == 0

        source_tables = {
            "time_entry": ("time_entry", "time_entry_id"),
            "leave_record": ("leave_record", "leave_id"),
            "allowance": ("allowance", "allowance_id"),
            "deduction": ("deduction", "deduction_id"),
        }
        for source_type, (table, id_column) in source_tables.items():
            invalid_links = connection.execute(
                f"""
                SELECT count(*)
                FROM payroll_input_source AS source
                JOIN payroll_input AS input USING (payroll_input_id)
                LEFT JOIN "{table}" AS record
                  ON record."{id_column}" = source.source_id
                 AND record.employee_id = input.employee_id
                 AND record.period_id = input.period_id
                WHERE source.source_type = ? AND record."{id_column}" IS NULL
                """,
                (source_type,),
            ).fetchone()[0]
            assert invalid_links == 0
    finally:
        connection.close()


def test_starter_generation_labels_anomalies_and_writes_manifest(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "starter"
    summary = generate_dataset(
        config=load_config(environment={}),
        employee_count=200,
        output_dir=output_dir,
    )

    with summary.ground_truth_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
    assert reader.fieldnames == [
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
    ]
    assert rows
    assert {row["expected_decision"] for row in rows} == {"FLAG", "PASS"}
    assert {row["issue_type"] for row in rows} == {
        "hours_exceed_period_max",
        "duplicate_allowance",
        "unapproved_time_exported",
        "leave_deduction_applied_twice",
        "totals_fail_to_reconcile",
        "missing_bank",
        "missing_tax",
        "duplicate_hours",
        "outlier_hours",
        "boundary_exact_max_hours",
        "boundary_legitimate_correction",
        "boundary_legitimate_resubmission",
    }
    assert summary.manifest_path.is_file()
    assert summary.checksums["paygate.db"]
    manifest = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
    assert manifest["seed"] == 20261022
    assert manifest["parameters"]["employee_count"] == 200
    assert manifest["row_counts"] == summary.table_counts
    assert {
        "backend/db/schema.sql",
        "data/seed/pay_groups.csv",
        "data/seed/allowance_types.csv",
        "data/seed/deduction_types.csv",
    }.issubset(manifest["sha256"])
    assert summary.table_counts["exception"] == 0
    assert summary.table_counts["validation_run"] == 0
    assert summary.table_counts["validation_rule"] == 0
