"""Small schema-backed database factory shared by validation tests."""

from pathlib import Path
import sqlite3
from typing import Any

from backend.db.connection import get_connection


SCHEMA_PATH = Path(__file__).parents[1] / "db" / "schema.sql"


def create_validation_database(path: Path) -> sqlite3.Connection:
    """Create one clean, minimal payroll period with a consistent export."""
    conn = get_connection(path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO pay_group VALUES (?, ?, ?, ?, ?, ?)",
        ("PG-001", "Test group", "monthly", 184.0, 10.0, 1.5),
    )
    conn.execute(
        """
        INSERT INTO employee
            (employee_id, full_name, employment_type, pay_group_id, hire_date,
             termination_date, base_rate_minor, bank_account, bank_routing,
             tax_id, status, effective_from, effective_to)
        VALUES (?, ?, 'hourly', ?, ?, NULL, ?, ?, ?, ?, 'active', ?, NULL)
        """,
        (
            "EMP-000001", "Synthetic Employee 1", "PG-001", "2026-01-01",
            1000, "acct-1", "route-1", "tax-1", "2026-01-01",
        ),
    )
    conn.execute(
        "INSERT INTO pay_period VALUES (?, ?, ?, 'OPEN')",
        ("PP-2026-01", "2026-01-01", "2026-01-31"),
    )
    conn.execute(
        "INSERT INTO paygroup_period_calendar VALUES (?, ?, ?, ?, 'OPEN')",
        ("PG-001", "PP-2026-01", "2026-01-25", "2026-02-01"),
    )
    conn.execute(
        "INSERT INTO allowance_type VALUES (?, ?, ?, 'active')",
        ("ALT-001", "Meal", 500),
    )
    conn.execute(
        "INSERT INTO allowance_type VALUES (?, ?, ?, 'active')",
        ("ALT-002", "Transit", 700),
    )
    conn.execute(
        "INSERT INTO deduction_type VALUES (?, ?, ?, 'active')",
        ("DET-001", "Benefit", 200),
    )
    conn.execute(
        """
        INSERT INTO employee_allowance_eligibility
            (employee_id, allowance_type_id, effective_from, effective_to)
        VALUES ('EMP-000001', 'ALT-001', '2026-01-01', NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO payroll_input
            (payroll_input_id, employee_id, period_id, regular_hours, ot_hours,
             gross_minor, deductions_minor, net_minor, status, input_hash)
        VALUES
            ('PIN-EMP-000001-2026-01', 'EMP-000001', 'PP-2026-01',
             8, 0, 8000, 0, 8000, 'APPROVED', 'test-hash')
        """
    )
    conn.execute(
        """
        INSERT INTO time_entry
            (time_entry_id, employee_id, period_id, work_date, hours,
             entry_type, status, submission_seq, supersedes_id, submitted_at,
             approved_by)
        VALUES
            ('TIME-EMP-000001-2026-01-05', 'EMP-000001', 'PP-2026-01',
             '2026-01-05', 8, 'REGULAR', 'APPROVED', 1, NULL,
             '2026-01-05T17:00:00', 'MGR-PG-001')
        """
    )
    conn.execute(
        """
        INSERT INTO payroll_input_source
            (payroll_input_id, source_type, source_id)
        VALUES ('PIN-EMP-000001-2026-01', 'time_entry',
                'TIME-EMP-000001-2026-01-05')
        """
    )
    conn.execute(
        """
        INSERT INTO payroll_export
            (export_id, pay_group_id, period_id, status, line_count,
             total_net_minor, created_at)
        VALUES ('PEX-2026-000001', 'PG-001', 'PP-2026-01', 'RELEASED',
                1, 8000, '2026-02-01T09:00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO payroll_export_line (export_id, payroll_input_id, amount_minor)
        VALUES ('PEX-2026-000001', 'PIN-EMP-000001-2026-01', 8000)
        """
    )
    conn.commit()
    return conn


def add_employee(conn: sqlite3.Connection, employee_id: str) -> None:
    """Add an hourly peer employee for pay-group statistics tests."""
    conn.execute(
        """
        INSERT INTO employee
            (employee_id, full_name, employment_type, pay_group_id, hire_date,
             base_rate_minor, bank_account, bank_routing, tax_id, status,
             effective_from)
        VALUES (?, ?, 'hourly', 'PG-001', '2026-01-01', 1000, 'acct',
                'route', 'tax', 'active', '2026-01-01')
        """,
        (employee_id, f"Synthetic {employee_id}"),
    )


def add_time_entry(
    conn: sqlite3.Connection,
    employee_id: str,
    work_date: str,
    *,
    hours: float = 8,
    entry_type: str = "REGULAR",
    status: str = "APPROVED",
    revision: str = "",
    supersedes_id: str | None = None,
    period_id: str = "PP-2026-01",
) -> str:
    """Add a time record and return its ID."""
    time_entry_id = f"TIME-{employee_id}-{work_date}{revision}"
    conn.execute(
        """
        INSERT INTO time_entry
            (time_entry_id, employee_id, period_id, work_date, hours,
             entry_type, status, submission_seq, supersedes_id, submitted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-01-05T17:00:00')
        """,
        (
            time_entry_id, employee_id, period_id, work_date, hours,
            entry_type, status, 2 if supersedes_id else 1, supersedes_id,
        ),
    )
    return time_entry_id


def add_leave(
    conn: sqlite3.Connection,
    leave_id: str = "LV-000001",
    *,
    employee_id: str = "EMP-000001",
    period_id: str = "PP-2026-01",
    start_date: str = "2026-01-10",
    end_date: str = "2026-01-10",
    status: str = "APPROVED",
) -> None:
    conn.execute(
        """
        INSERT INTO leave_record
            (leave_id, employee_id, period_id, leave_type, start_date, end_date,
             days, paid_flag, status)
        VALUES (?, ?, ?, 'ANNUAL', ?, ?, 1, 1, ?)
        """,
        (leave_id, employee_id, period_id, start_date, end_date, status),
    )


def first_rule_finding(findings: list[Any], rule_id: str) -> Any:
    """Select a specific rule's first finding from a combined rule execution."""
    return next(finding for finding in findings if finding.rule_id == rule_id)
