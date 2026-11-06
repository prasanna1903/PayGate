"""Derive payroll inputs and source links with SQLite aggregation."""

from __future__ import annotations

import hashlib
import sqlite3

from backend.generator.ids import build_payroll_input_id


def _insert_input_skeletons(connection: sqlite3.Connection) -> None:
    rows = []
    employee_periods = connection.execute(
        "SELECT employee.employee_id, pay_period.period_id, pay_period.start_date "
        "FROM employee JOIN pay_period "
        "ON employee.effective_from <= pay_period.end_date "
        "ORDER BY employee.employee_id, pay_period.start_date"
    ).fetchall()
    for employee_id, period_id, start_date in employee_periods:
        rows.append(
            (
                build_payroll_input_id(
                    employee_id,
                    int(start_date[:4]),
                    int(start_date[5:7]),
                ),
                employee_id,
                period_id,
            )
        )
    connection.executemany(
        "INSERT INTO payroll_input "
        "(payroll_input_id, employee_id, period_id, regular_hours, ot_hours, "
        "gross_minor, deductions_minor, net_minor, status, input_hash) "
        "VALUES (?, ?, ?, 0, 0, 0, 0, 0, 'AGGREGATED', '') "
        "ON CONFLICT(employee_id, period_id) DO NOTHING",
        rows,
    )


def _aggregate_amounts(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        WITH
        time_totals AS (
            SELECT
                employee_id,
                period_id,
                SUM(CASE
                    WHEN entry_type = 'REGULAR' THEN MIN(hours, 8.0)
                    ELSE 0
                END) AS regular_hours,
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
            FROM allowance
            WHERE status = 'APPROVED'
            GROUP BY employee_id, period_id
        ),
        leave_deduction_totals AS (
            SELECT employee_id, period_id, SUM(amount_minor) AS amount_minor
            FROM deduction
            WHERE status = 'APPROVED' AND source_leave_id IS NOT NULL
            GROUP BY employee_id, period_id
        ),
        deduction_totals AS (
            SELECT employee_id, period_id, SUM(amount_minor) AS amount_minor
            FROM deduction
            WHERE status = 'APPROVED' AND source_leave_id IS NULL
            GROUP BY employee_id, period_id
        ),
        amounts AS (
            SELECT
                payroll_input.payroll_input_id,
                COALESCE(time_totals.regular_hours, 0) AS regular_hours,
                COALESCE(time_totals.ot_hours, 0) AS ot_hours,
                CASE
                    WHEN employee.employment_type = 'hourly' THEN
                        COALESCE(time_totals.regular_hours, 0)
                            * employee.base_rate_minor
                        + COALESCE(time_totals.ot_hours, 0)
                            * employee.base_rate_minor * pay_group.ot_multiplier
                    ELSE
                        employee.base_rate_minor
                        + COALESCE(time_totals.ot_hours, 0)
                            * employee.base_rate_minor / 160.0
                            * pay_group.ot_multiplier
                END
                + COALESCE(allowance_totals.amount_minor, 0)
                - COALESCE(leave_deduction_totals.amount_minor, 0)
                    AS gross_amount,
                COALESCE(deduction_totals.amount_minor, 0) AS deductions_amount
            FROM payroll_input
            JOIN employee USING (employee_id)
            JOIN pay_group USING (pay_group_id)
            LEFT JOIN time_totals USING (employee_id, period_id)
            LEFT JOIN allowance_totals USING (employee_id, period_id)
            LEFT JOIN leave_deduction_totals USING (employee_id, period_id)
            LEFT JOIN deduction_totals USING (employee_id, period_id)
        )
        UPDATE payroll_input
        SET
            regular_hours = (
                SELECT regular_hours FROM amounts
                WHERE amounts.payroll_input_id = payroll_input.payroll_input_id
            ),
            ot_hours = (
                SELECT ot_hours FROM amounts
                WHERE amounts.payroll_input_id = payroll_input.payroll_input_id
            ),
            gross_minor = (
                SELECT CAST(ROUND(gross_amount) AS INTEGER) FROM amounts
                WHERE amounts.payroll_input_id = payroll_input.payroll_input_id
            ),
            deductions_minor = (
                SELECT CAST(ROUND(deductions_amount) AS INTEGER) FROM amounts
                WHERE amounts.payroll_input_id = payroll_input.payroll_input_id
            ),
            net_minor = (
                SELECT CAST(ROUND(gross_amount - deductions_amount) AS INTEGER)
                FROM amounts
                WHERE amounts.payroll_input_id = payroll_input.payroll_input_id
            )
        """
    )


def _insert_source_links(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO payroll_input_source
            (payroll_input_id, source_type, source_id)
        SELECT input.payroll_input_id, 'time_entry', entry.time_entry_id
        FROM payroll_input AS input
        JOIN time_entry AS entry
          ON entry.employee_id = input.employee_id
         AND entry.period_id = input.period_id
        WHERE entry.status = 'APPROVED'
        ORDER BY input.payroll_input_id, entry.time_entry_id
        ON CONFLICT (payroll_input_id, source_type, source_id) DO NOTHING
        """
    )
    connection.execute(
        """
        INSERT INTO payroll_input_source
            (payroll_input_id, source_type, source_id)
        SELECT input.payroll_input_id, 'leave_record', leave.leave_id
        FROM payroll_input AS input
        JOIN leave_record AS leave
          ON leave.employee_id = input.employee_id
         AND leave.period_id = input.period_id
        WHERE leave.status = 'APPROVED'
        ORDER BY input.payroll_input_id, leave.leave_id
        ON CONFLICT (payroll_input_id, source_type, source_id) DO NOTHING
        """
    )
    connection.execute(
        """
        INSERT INTO payroll_input_source
            (payroll_input_id, source_type, source_id)
        SELECT input.payroll_input_id, 'allowance', allowance.allowance_id
        FROM payroll_input AS input
        JOIN allowance
          ON allowance.employee_id = input.employee_id
         AND allowance.period_id = input.period_id
        WHERE allowance.status = 'APPROVED'
        ORDER BY input.payroll_input_id, allowance.allowance_id
        ON CONFLICT (payroll_input_id, source_type, source_id) DO NOTHING
        """
    )
    connection.execute(
        """
        INSERT INTO payroll_input_source
            (payroll_input_id, source_type, source_id)
        SELECT input.payroll_input_id, 'deduction', deduction.deduction_id
        FROM payroll_input AS input
        JOIN deduction
          ON deduction.employee_id = input.employee_id
         AND deduction.period_id = input.period_id
        WHERE deduction.status = 'APPROVED'
        ORDER BY input.payroll_input_id, deduction.deduction_id
        ON CONFLICT (payroll_input_id, source_type, source_id) DO NOTHING
        """
    )


def _refresh_hashes(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT payroll_input_id, regular_hours, ot_hours, gross_minor, "
        "deductions_minor, net_minor FROM payroll_input ORDER BY payroll_input_id"
    ).fetchall()
    for row in rows:
        serialized = "|".join(str(value) for value in row)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        connection.execute(
            "UPDATE payroll_input SET input_hash = ? WHERE payroll_input_id = ?",
            (digest, row[0]),
        )


def aggregate_payroll_inputs(
    connection: sqlite3.Connection,
) -> None:
    """Insert or re-aggregate payroll inputs using SQL over approved sources."""
    _insert_input_skeletons(connection)
    _aggregate_amounts(connection)
    _insert_source_links(connection)
    _refresh_hashes(connection)
