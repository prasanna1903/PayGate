"""Tests for PayGate database schema integrity."""

import sqlite3
from pathlib import Path
import re

import pytest

from backend.db.connection import get_connection


SCHEMA_PATH = Path(__file__).parents[1] / "db" / "schema.sql"
EXPECTED_TABLES = {
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

REQUIRED_COLUMNS = {
    "employee": {
        "employee_id", "full_name", "employment_type", "pay_group_id", "hire_date",
        "termination_date", "base_rate_minor", "bank_account", "bank_routing",
        "tax_id", "status", "effective_from", "effective_to",
    },
    "pay_group": {
        "pay_group_id", "name", "pay_frequency", "max_hours_per_period",
        "max_hours_per_day", "ot_multiplier",
    },
    "pay_period": {"period_id", "start_date", "end_date", "status"},
    "paygroup_period_calendar": {
        "pay_group_id", "period_id", "cutoff_date", "pay_date", "status",
    },
    "leave_record": {
        "leave_id", "employee_id", "period_id", "leave_type", "start_date",
        "end_date", "days", "paid_flag", "status",
    },
    "time_entry": {
        "time_entry_id", "employee_id", "period_id", "work_date", "hours",
        "entry_type", "status", "submission_seq", "supersedes_id",
        "submitted_at", "approved_by",
    },
    "allowance_type": {"allowance_type_id"},
    "deduction_type": {"deduction_type_id"},
    "employee_allowance_eligibility": {
        "employee_id", "allowance_type_id", "effective_from", "effective_to",
    },
    "employee_deduction_enrollment": {
        "employee_id", "deduction_type_id", "effective_from", "effective_to",
    },
    "allowance": {
        "allowance_id", "employee_id", "period_id", "allowance_type_id",
        "amount_minor", "status",
    },
    "deduction": {
        "deduction_id", "employee_id", "period_id", "deduction_type_id",
        "amount_minor", "source_leave_id", "status",
    },
    "payroll_input": {
        "payroll_input_id", "employee_id", "period_id", "regular_hours",
        "ot_hours", "gross_minor", "deductions_minor", "net_minor", "status",
        "input_hash",
    },
    "payroll_input_source": {"payroll_input_id", "source_type", "source_id"},
    "validation_rule": {
        "rule_id", "name", "severity", "blocking_flag", "params_json", "version",
        "active",
    },
    "validation_run": {
        "run_id", "started_at", "rule_versions_json", "params_json", "trigger",
    },
    "exception": {
        "exception_id", "run_id", "rule_id", "entity_type", "entity_id",
        "employee_id", "period_id", "severity", "status", "evidence_json",
        "created_at",
    },
    "approval": {
        "approval_id", "target_type", "target_id", "approver_role", "approver_id",
        "decision", "comment", "decided_at",
    },
    "payroll_export": {
        "export_id", "pay_group_id", "period_id", "status", "line_count",
        "total_net_minor", "created_at",
    },
    "payroll_export_line": {"export_id", "payroll_input_id", "amount_minor"},
    "state_event": {
        "event_id", "entity_type", "entity_id", "from_state", "to_state", "actor",
        "reason", "occurred_at",
    },
}

REQUIRED_PRIMARY_KEYS = {
    "employee": ("employee_id",),
    "pay_group": ("pay_group_id",),
    "pay_period": ("period_id",),
    "paygroup_period_calendar": ("pay_group_id", "period_id"),
    "leave_record": ("leave_id",),
    "time_entry": ("time_entry_id",),
    "allowance_type": ("allowance_type_id",),
    "deduction_type": ("deduction_type_id",),
    "allowance": ("allowance_id",),
    "deduction": ("deduction_id",),
    "payroll_input": ("payroll_input_id",),
    "payroll_input_source": ("payroll_input_id", "source_type", "source_id"),
    "validation_rule": ("rule_id",),
    "validation_run": ("run_id",),
    "exception": ("exception_id",),
    "approval": ("approval_id",),
    "payroll_export": ("export_id",),
    "state_event": ("event_id",),
}

REQUIRED_FOREIGN_KEYS = {
    "employee": {("pay_group_id", "pay_group", "pay_group_id")},
    "paygroup_period_calendar": {
        ("pay_group_id", "pay_group", "pay_group_id"),
        ("period_id", "pay_period", "period_id"),
    },
    "leave_record": {
        ("employee_id", "employee", "employee_id"),
        ("period_id", "pay_period", "period_id"),
    },
    "time_entry": {
        ("employee_id", "employee", "employee_id"),
        ("period_id", "pay_period", "period_id"),
        ("supersedes_id", "time_entry", "time_entry_id"),
    },
    "employee_allowance_eligibility": {
        ("employee_id", "employee", "employee_id"),
        ("allowance_type_id", "allowance_type", "allowance_type_id"),
    },
    "employee_deduction_enrollment": {
        ("employee_id", "employee", "employee_id"),
        ("deduction_type_id", "deduction_type", "deduction_type_id"),
    },
    "allowance": {
        ("employee_id", "employee", "employee_id"),
        ("period_id", "pay_period", "period_id"),
        ("allowance_type_id", "allowance_type", "allowance_type_id"),
    },
    "deduction": {
        ("employee_id", "employee", "employee_id"),
        ("period_id", "pay_period", "period_id"),
        ("deduction_type_id", "deduction_type", "deduction_type_id"),
        ("source_leave_id", "leave_record", "leave_id"),
    },
    "payroll_input": {
        ("employee_id", "employee", "employee_id"),
        ("period_id", "pay_period", "period_id"),
    },
    "payroll_input_source": {
        ("payroll_input_id", "payroll_input", "payroll_input_id"),
    },
    "exception": {
        ("run_id", "validation_run", "run_id"),
        ("rule_id", "validation_rule", "rule_id"),
        ("employee_id", "employee", "employee_id"),
        ("period_id", "pay_period", "period_id"),
        ("approval_id", "approval", "approval_id"),
    },
    "payroll_export": {
        ("pay_group_id", "pay_group", "pay_group_id"),
        ("period_id", "pay_period", "period_id"),
    },
    "payroll_export_line": {
        ("export_id", "payroll_export", "export_id"),
        ("payroll_input_id", "payroll_input", "payroll_input_id"),
    },
}

LIFECYCLE_STATES = {
    "time_entry": {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"},
    "payroll_input": {"AGGREGATED", "VALIDATED", "BLOCKED", "APPROVED", "EXPORTED"},
    "exception": {"OPEN", "ACKNOWLEDGED", "RESOLVED", "WAIVED", "SUPERSEDED"},
    "payroll_export": {"CREATED", "RELEASED"},
}


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _primary_key(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        row[1]
        for row in sorted(
            connection.execute(f"PRAGMA table_info({table})"),
            key=lambda row: row[5],
        )
        if row[5]
    )


def _foreign_keys(connection: sqlite3.Connection, table: str) -> set[tuple[str, str, str]]:
    return {
        (row[3], row[2], row[4])
        for row in connection.execute(f"PRAGMA foreign_key_list({table})")
    }


def _unique_keys(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    keys = set()
    for index in connection.execute(f"PRAGMA index_list({table})"):
        if index[2]:
            keys.add(
                tuple(
                    row[2]
                    for row in connection.execute(f"PRAGMA index_info({index[1]})")
                )
            )
    return keys


def _check_values(connection: sqlite3.Connection, table: str) -> set[str]:
    create_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()[0]
    for match in re.finditer(r"\bstatus\s+IN\s*\(([^)]*)\)", create_sql, re.IGNORECASE):
        return set(re.findall(r"'([^']+)'", match.group(1)))
    raise AssertionError(f"{table} has no status CHECK constraint")


def _insert_payroll_input_parents(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO pay_group "
        "(pay_group_id, name, pay_frequency, max_hours_per_period, "
        "max_hours_per_day, ot_multiplier) "
        "VALUES ('PG-001', 'Default', 'monthly', 200, 12, 1.5)"
    )
    connection.execute(
        "INSERT INTO employee "
        "(employee_id, full_name, employment_type, pay_group_id, hire_date, "
        "base_rate_minor, status, effective_from) "
        "VALUES ('EMP-000001', 'Ada Lovelace', 'hourly', 'PG-001', "
        "'2026-01-01', 100, 'active', '2026-01-01')"
    )
    connection.execute(
        "INSERT INTO pay_period (period_id, start_date, end_date, status) "
        "VALUES ('PP-2026-01', '2026-01-01', '2026-01-31', 'OPEN')"
    )
    connection.execute(
        "INSERT INTO payroll_input "
        "(payroll_input_id, employee_id, period_id, regular_hours, ot_hours, "
        "gross_minor, deductions_minor, net_minor, status, input_hash) "
        "VALUES ('PIN-EMP-000001-2026-01', 'EMP-000001', 'PP-2026-01', "
        "40, 0, 4000, 0, 4000, 'AGGREGATED', 'hash')"
    )


def test_schema_has_all_blueprint_tables_and_no_ground_truth_table() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection)
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert actual_tables == EXPECTED_TABLES
    finally:
        connection.close()


def test_blueprint_columns_and_primary_keys_are_present_for_all_tables() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection)
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert actual_tables == EXPECTED_TABLES

        for table, required_columns in REQUIRED_COLUMNS.items():
            actual_columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            assert required_columns <= actual_columns, table

        for table, required_key in REQUIRED_PRIMARY_KEYS.items():
            assert _primary_key(connection, table) == required_key, table
    finally:
        connection.close()


def test_blueprint_foreign_keys_and_payroll_input_uniqueness() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection)

        for table in EXPECTED_TABLES:
            assert _foreign_keys(connection, table) == REQUIRED_FOREIGN_KEYS.get(
                table, set()
            ), table

        assert ("employee_id", "period_id") in _unique_keys(
            connection, "payroll_input"
        )
    finally:
        connection.close()


def test_schema_checks_the_explicit_lifecycle_statuses() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection)
        for table, expected_states in LIFECYCLE_STATES.items():
            assert _check_values(connection, table) == expected_states, table
    finally:
        connection.close()


def test_payroll_input_source_requires_and_uniquely_keys_source_records() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection)
        _insert_payroll_input_parents(connection)

        columns = {
            row[1]: {"not_null": row[3], "primary_key_order": row[5]}
            for row in connection.execute("PRAGMA table_info(payroll_input_source)")
        }
        assert columns["source_type"] == {"not_null": 1, "primary_key_order": 2}
        assert columns["source_id"] == {"not_null": 1, "primary_key_order": 3}

        link = (
            "PIN-EMP-000001-2026-01",
            "time_entry",
            "TIME-EMP-000001-2026-01-05",
        )
        connection.execute(
            "INSERT INTO payroll_input_source "
            "(payroll_input_id, source_type, source_id) VALUES (?, ?, ?)",
            link,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO payroll_input_source "
                "(payroll_input_id, source_type, source_id) VALUES (?, ?, ?)",
                link,
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO payroll_input_source "
                "(payroll_input_id, source_type, source_id) "
                "VALUES (?, ?, NULL)",
                (link[0], link[1]),
            )
    finally:
        connection.close()


def test_database_connection_enables_foreign_keys() -> None:
    connection = get_connection(":memory:")
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        _create_schema(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO employee "
                "(employee_id, full_name, employment_type, pay_group_id, "
                "hire_date, base_rate_minor, status, effective_from) "
                "VALUES ('EMP-000001', 'Ada Lovelace', 'hourly', 'missing', "
                "'2026-01-01', 100, 'active', '2026-01-01')"
            )
    finally:
        connection.close()


def test_state_event_rows_cannot_be_updated_or_deleted() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection)
        connection.execute(
            "INSERT INTO state_event "
            "(event_id, entity_type, entity_id, from_state, to_state, actor, "
            "reason, occurred_at) "
            "VALUES ('EVT-000001', 'payroll_input', 'PIN-1', NULL, "
            "'AGGREGATED', 'system', 'created', '2026-01-01T00:00:00')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE state_event SET reason = 'changed' "
                "WHERE event_id = 'EVT-000001'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM state_event WHERE event_id = 'EVT-000001'"
            )
    finally:
        connection.close()


def test_lifecycle_status_checks_reject_unknown_values() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                "INSERT INTO time_entry "
                "(time_entry_id, employee_id, period_id, work_date, hours, "
                "entry_type, status, submission_seq) "
                "VALUES ('TIME-1', 'EMP-1', 'PP-2026-01', '2026-01-01', "
                "8, 'regular', 'PENDING', 1)"
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                "INSERT INTO payroll_input "
                "(payroll_input_id, employee_id, period_id, regular_hours, "
                "ot_hours, gross_minor, deductions_minor, net_minor, status, "
                "input_hash) VALUES ('PIN-1', 'EMP-1', 'PP-2026-01', 0, 0, "
                "0, 0, 0, 'PENDING', 'hash')"
            )
    finally:
        connection.close()
