"""Tests for core PayGate database schema integrity."""

import sqlite3
from pathlib import Path

import pytest

from backend.db.connection import get_connection


SCHEMA_PATH = Path(__file__).parents[1] / "db" / "schema.sql"


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_payroll_input_source_rejects_duplicate_source_links() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection)
        connection.execute(
            "INSERT INTO pay_group (pay_group_id, name, pay_frequency) "
            "VALUES ('PG-001', 'Default', 'monthly')"
        )
        connection.execute(
            "INSERT INTO employee "
            "(employee_id, pay_group_id, first_name, last_name, hire_date) "
            "VALUES ('EMP-000001', 'PG-001', 'Ada', 'Lovelace', '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO pay_period (pay_period_id, start_date, end_date, pay_date) "
            "VALUES ('PP-2026-01', '2026-01-01', '2026-01-31', '2026-02-01')"
        )
        connection.execute(
            "INSERT INTO payroll_input "
            "(payroll_input_id, employee_id, pay_period_id, input_type, amount_minor) "
            "VALUES ('PIN-EMP-000001-2026-01', 'EMP-000001', 'PP-2026-01', 'salary', 100)"
        )
        connection.execute(
            "INSERT INTO time_entry "
            "(time_entry_id, employee_id, work_date, worked_minutes) "
            "VALUES ('TIME-EMP-000001-2026-01-05', 'EMP-000001', '2026-01-05', 480)"
        )

        source_link = (
            "PIN-EMP-000001-2026-01",
            "TIME-EMP-000001-2026-01-05",
            None,
            None,
            None,
        )
        connection.execute(
            "INSERT INTO payroll_input_source "
            "(payroll_input_id, time_entry_id, leave_id, allowance_id, deduction_id) "
            "VALUES (?, ?, ?, ?, ?)",
            source_link,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO payroll_input_source "
                "(payroll_input_id, time_entry_id, leave_id, allowance_id, deduction_id) "
                "VALUES (?, ?, ?, ?, ?)",
                source_link,
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
                "(employee_id, pay_group_id, first_name, last_name, hire_date) "
                "VALUES ('EMP-000001', 'missing', 'Ada', 'Lovelace', '2026-01-01')"
            )
    finally:
        connection.close()
