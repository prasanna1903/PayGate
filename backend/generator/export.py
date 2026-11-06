"""Create deterministic baseline approvals, exports, and history rows."""

from __future__ import annotations

from datetime import date, datetime, time
import sqlite3
from typing import Any

from backend.generator.ids import (
    build_approval_id,
    build_payroll_export_id,
    build_state_event_id,
)


def _next_number(connection: sqlite3.Connection, table: str, column: str) -> int:
    value = connection.execute(
        f'SELECT MAX(CAST(substr("{column}", instr("{column}", \'-\') + 1) AS INTEGER)) '
        f'FROM "{table}"'
    ).fetchone()[0]
    return int(value or 0) + 1


def _stamp(value: str, hour: int = 17) -> str:
    day = date.fromisoformat(value)
    return datetime.combine(day, time(hour=hour)).isoformat(timespec="seconds")


def create_baseline_exports(connection: sqlite3.Connection) -> None:
    """Approve clean derived inputs and release one export per populated group-period."""
    approval_number = _next_number(connection, "approval", "approval_id")
    event_number = _next_number(connection, "state_event", "event_id")
    approval_rows: list[tuple[Any, ...]] = []
    event_rows: list[tuple[Any, ...]] = []
    input_rows = connection.execute(
        """
        SELECT input.payroll_input_id, period.end_date
        FROM payroll_input AS input
        JOIN pay_period AS period USING (period_id)
        ORDER BY input.payroll_input_id
        """
    ).fetchall()
    for payroll_input_id, end_date in input_rows:
        decided_at = _stamp(end_date, 18)
        approval_rows.append(
            (
                build_approval_id(approval_number),
                "payroll_input",
                payroll_input_id,
                "HR",
                "HR-001",
                "APPROVED",
                "Clean baseline payroll input approved",
                decided_at,
            )
        )
        approval_number += 1
        event_rows.extend(
            (
                (
                    build_state_event_id(event_number),
                    "payroll_input",
                    payroll_input_id,
                    "AGGREGATED",
                    "VALIDATED",
                    "system",
                    "Baseline source aggregation completed without planted anomalies",
                    _stamp(end_date, 17),
                ),
                (
                    build_state_event_id(event_number + 1),
                    "payroll_input",
                    payroll_input_id,
                    "VALIDATED",
                    "APPROVED",
                    "HR-001",
                    "Clean baseline input approved",
                    decided_at,
                ),
            )
        )
        event_number += 2
    connection.executemany(
        "INSERT INTO approval "
        "(approval_id, target_type, target_id, approver_role, approver_id, "
        "decision, comment, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        approval_rows,
    )
    connection.executemany(
        "INSERT INTO state_event "
        "(event_id, entity_type, entity_id, from_state, to_state, actor, reason, "
        "occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        event_rows,
    )
    connection.execute(
        "UPDATE payroll_input SET status = 'APPROVED' WHERE status = 'AGGREGATED'"
    )

    exports = connection.execute(
        """
        SELECT DISTINCT
            employee.pay_group_id,
            input.period_id,
            period.start_date,
            calendar.pay_date
        FROM payroll_input AS input
        JOIN employee USING (employee_id)
        JOIN pay_period AS period USING (period_id)
        JOIN paygroup_period_calendar AS calendar
          ON calendar.pay_group_id = employee.pay_group_id
         AND calendar.period_id = input.period_id
        WHERE input.status = 'APPROVED'
        ORDER BY employee.pay_group_id, input.period_id
        """
    ).fetchall()
    export_number = 1
    event_rows = []
    for pay_group_id, period_id, start_date, pay_date in exports:
        export_id = build_payroll_export_id(int(start_date[:4]), export_number)
        export_number += 1
        created_at = _stamp(pay_date, 9)
        connection.execute(
            "INSERT INTO payroll_export "
            "(export_id, pay_group_id, period_id, status, line_count, "
            "total_net_minor, created_at) "
            "VALUES (?, ?, ?, 'CREATED', 0, 0, ?)",
            (export_id, pay_group_id, period_id, created_at),
        )
        connection.execute(
            """
            INSERT INTO payroll_export_line (export_id, payroll_input_id, amount_minor)
            SELECT ?, input.payroll_input_id, input.net_minor
            FROM payroll_input AS input
            JOIN employee USING (employee_id)
            WHERE employee.pay_group_id = ?
              AND input.period_id = ?
              AND input.status = 'APPROVED'
            ORDER BY input.payroll_input_id
            """,
            (export_id, pay_group_id, period_id),
        )
        totals = connection.execute(
            "SELECT count(*), coalesce(sum(amount_minor), 0) "
            "FROM payroll_export_line WHERE export_id = ?",
            (export_id,),
        ).fetchone()
        connection.execute(
            "UPDATE payroll_export SET status = 'RELEASED', line_count = ?, "
            "total_net_minor = ? WHERE export_id = ?",
            (totals[0], totals[1], export_id),
        )
        event_rows.extend(
            (
                (
                    build_state_event_id(event_number),
                    "payroll_export",
                    export_id,
                    None,
                    "CREATED",
                    "system",
                    "Baseline export created",
                    created_at,
                ),
                (
                    build_state_event_id(event_number + 1),
                    "payroll_export",
                    export_id,
                    "CREATED",
                    "RELEASED",
                    "system",
                    "Clean baseline export released",
                    created_at,
                ),
            )
        )
        event_number += 2
    connection.executemany(
        "INSERT INTO state_event "
        "(event_id, entity_type, entity_id, from_state, to_state, actor, reason, "
        "occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        event_rows,
    )


def synchronize_baseline_lines(connection: sqlite3.Connection) -> None:
    """Keep baseline export lines aligned after anomaly-driven SQL re-aggregation."""
    connection.execute(
        """
        UPDATE payroll_export_line
        SET amount_minor = (
            SELECT net_minor FROM payroll_input
            WHERE payroll_input.payroll_input_id =
                payroll_export_line.payroll_input_id
        )
        """
    )
    connection.execute(
        """
        UPDATE payroll_export
        SET
            line_count = (
                SELECT count(*) FROM payroll_export_line
                WHERE payroll_export_line.export_id = payroll_export.export_id
            ),
            total_net_minor = (
                SELECT coalesce(sum(amount_minor), 0) FROM payroll_export_line
                WHERE payroll_export_line.export_id = payroll_export.export_id
            )
        """
    )
