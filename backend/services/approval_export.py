"""Transactional payroll approval, exception waiver, and export workflows."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from collections.abc import Iterator
from typing import Any

from backend.generator.ids import (
    build_approval_id,
    build_payroll_export_id,
    build_state_event_id,
)


class WorkflowError(Exception):
    """A business-rule or request error safe to return to an API client."""

    def __init__(
        self,
        status_code: int,
        message: str,
        reasons: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.reasons = reasons or []


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Run one operation atomically, reserving SQLite's write lock up front."""
    if connection.in_transaction:
        connection.execute("SAVEPOINT paygate_workflow")
        try:
            yield
            connection.execute("RELEASE SAVEPOINT paygate_workflow")
        except BaseException:
            connection.execute("ROLLBACK TO SAVEPOINT paygate_workflow")
            connection.execute("RELEASE SAVEPOINT paygate_workflow")
            raise
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _next_number(
    connection: sqlite3.Connection, table: str, column: str
) -> int:
    value = connection.execute(
        f'SELECT MAX(CAST(substr("{column}", instr("{column}", \'-\') + 1) '
        f'AS INTEGER)) FROM "{table}"'
    ).fetchone()[0]
    return int(value or 0) + 1


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(400, f"{field} must not be empty.")
    return value.strip()


def _append_event(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: str,
    from_state: str | None,
    to_state: str,
    actor: str,
    reason: str,
    occurred_at: str,
) -> None:
    event_number = _next_number(connection, "state_event", "event_id")
    connection.execute(
        """
        INSERT INTO state_event
            (event_id, entity_type, entity_id, from_state, to_state, actor,
             reason, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            build_state_event_id(event_number),
            entity_type,
            entity_id,
            from_state,
            to_state,
            actor,
            reason,
            occurred_at,
        ),
    )


def _insert_approval(
    connection: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
    approver_role: str,
    approver_id: str,
    decision: str,
    comment: str,
    decided_at: str,
) -> str:
    approval_id = build_approval_id(
        _next_number(connection, "approval", "approval_id")
    )
    connection.execute(
        """
        INSERT INTO approval
            (approval_id, target_type, target_id, approver_role, approver_id,
             decision, comment, decided_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            approval_id,
            target_type,
            target_id,
            approver_role,
            approver_id,
            decision,
            comment,
            decided_at,
        ),
    )
    return approval_id


def _exception_applies_to_input(
    connection: sqlite3.Connection,
    exception: tuple[Any, ...],
    *,
    payroll_input_id: str,
    employee_id: str,
    period_id: str,
) -> bool:
    (
        _exception_id,
        entity_type,
        entity_id,
        exception_employee_id,
        exception_period_id,
        evidence_json,
    ) = exception
    if entity_type == "payroll_input":
        return entity_id == payroll_input_id
    if entity_type == "payroll_export_line":
        evidence = json.loads(evidence_json)
        return isinstance(evidence, dict) and str(
            evidence.get("payroll_input_id", "")
        ) == payroll_input_id
    if entity_type == "payroll_export":
        export = connection.execute(
            "SELECT pay_group_id, period_id FROM payroll_export WHERE export_id = ?",
            (entity_id,),
        ).fetchone()
        if export is None or export[1] != period_id:
            return False
        pay_group_id = connection.execute(
            "SELECT pay_group_id FROM employee WHERE employee_id = ?",
            (employee_id,),
        ).fetchone()[0]
        return export[0] == pay_group_id
    if exception_employee_id is not None:
        return exception_employee_id == employee_id and (
            exception_period_id is None or exception_period_id == period_id
        )
    if exception_period_id is not None:
        return exception_period_id == period_id
    return False


def _blocking_exceptions(
    connection: sqlite3.Connection,
    payroll_input_id: str,
    employee_id: str,
    period_id: str,
) -> list[dict[str, str]]:
    exceptions = connection.execute(
        """
        SELECT exception.exception_id, exception.entity_type,
               exception.entity_id, exception.employee_id, exception.period_id,
               exception.evidence_json, exception.status, exception.rule_id
        FROM exception
        JOIN validation_rule USING (rule_id)
        WHERE validation_rule.blocking_flag = 1
          AND exception.status IN ('OPEN', 'ACKNOWLEDGED')
        ORDER BY exception.exception_id
        """
    ).fetchall()
    blockers: list[dict[str, str]] = []
    for row in exceptions:
        if _exception_applies_to_input(
            connection,
            row[:6],
            payroll_input_id=payroll_input_id,
            employee_id=employee_id,
            period_id=period_id,
        ):
            blockers.append(
                {
                    "code": "blocking_exception",
                    "message": (
                        f"Unresolved blocking exception {row[0]} "
                        f"({row[7]}, {row[6]})."
                    ),
                    "exception_id": row[0],
                }
            )
    return blockers


def approve_payroll_input(
    connection: sqlite3.Connection,
    payroll_input_id: str,
    *,
    approver_id: str,
    comment: str,
    approver_role: str = "HR",
) -> dict[str, str]:
    """Approve a validated input only when no associated blocking exception is open."""
    approver_id = _require_text(approver_id, "approver_id")
    comment = _require_text(comment, "comment")
    approver_role = _require_text(approver_role, "approver_role")

    with _transaction(connection):
        payroll_input = connection.execute(
            """
            SELECT employee_id, period_id, status
            FROM payroll_input WHERE payroll_input_id = ?
            """,
            (payroll_input_id,),
        ).fetchone()
        if payroll_input is None:
            raise WorkflowError(404, f"Payroll input {payroll_input_id} was not found.")
        employee_id, period_id, status = payroll_input
        if status not in ("VALIDATED", "BLOCKED"):
            raise WorkflowError(
                409,
                f"Payroll input {payroll_input_id} cannot be approved from status {status}.",
                [
                    {
                        "code": "invalid_input_status",
                        "message": (
                            f"Expected VALIDATED or BLOCKED; found {status}."
                        ),
                        "payroll_input_id": payroll_input_id,
                    }
                ],
            )

        blockers = _blocking_exceptions(
            connection, payroll_input_id, employee_id, period_id
        )
        if blockers:
            raise WorkflowError(
                409,
                f"Payroll input {payroll_input_id} has unresolved blocking exceptions.",
                blockers,
            )

        decided_at = _timestamp()
        approval_id = _insert_approval(
            connection,
            target_type="payroll_input",
            target_id=payroll_input_id,
            approver_role=approver_role,
            approver_id=approver_id,
            decision="APPROVED",
            comment=comment,
            decided_at=decided_at,
        )
        connection.execute(
            "UPDATE payroll_input SET status = 'APPROVED' "
            "WHERE payroll_input_id = ? AND status = 'VALIDATED'",
            (payroll_input_id,),
        )
        _append_event(
            connection,
            entity_type="payroll_input",
            entity_id=payroll_input_id,
            from_state=status,
            to_state="APPROVED",
            actor=approver_id,
            reason=comment,
            occurred_at=decided_at,
        )
    return {
        "approval_id": approval_id,
        "payroll_input_id": payroll_input_id,
        "status": "APPROVED",
        "approver_id": approver_id,
        "comment": comment,
    }


def waive_exception(
    connection: sqlite3.Connection,
    exception_id: str,
    *,
    approver_id: str,
    comment: str,
) -> dict[str, str]:
    """Waive one open blocking exception while retaining its audit history."""
    approver_id = _require_text(approver_id, "approver_id")
    comment = _require_text(comment, "comment")

    with _transaction(connection):
        exception = connection.execute(
            """
            SELECT exception.status, validation_rule.blocking_flag
            FROM exception
            JOIN validation_rule USING (rule_id)
            WHERE exception.exception_id = ?
            """,
            (exception_id,),
        ).fetchone()
        if exception is None:
            raise WorkflowError(404, f"Exception {exception_id} was not found.")
        status, blocking_flag = exception
        if not blocking_flag:
            raise WorkflowError(
                409, f"Exception {exception_id} is not classified as blocking."
            )
        if status not in ("OPEN", "ACKNOWLEDGED"):
            raise WorkflowError(
                409,
                f"Exception {exception_id} cannot be waived from status {status}.",
                [
                    {
                        "code": "invalid_exception_status",
                        "message": f"Expected OPEN or ACKNOWLEDGED; found {status}.",
                        "exception_id": exception_id,
                    }
                ],
            )

        decided_at = _timestamp()
        approval_id = _insert_approval(
            connection,
            target_type="exception",
            target_id=exception_id,
            approver_role="HR",
            approver_id=approver_id,
            decision="WAIVED",
            comment=comment,
            decided_at=decided_at,
        )
        connection.execute(
            """
            UPDATE exception
            SET status = 'WAIVED', approval_id = ?
            WHERE exception_id = ? AND status = ?
            """,
            (approval_id, exception_id, status),
        )
        _append_event(
            connection,
            entity_type="exception",
            entity_id=exception_id,
            from_state=status,
            to_state="WAIVED",
            actor=approver_id,
            reason=comment,
            occurred_at=decided_at,
        )
    return {
        "approval_id": approval_id,
        "exception_id": exception_id,
        "status": "WAIVED",
        "approver_id": approver_id,
        "comment": comment,
    }


def _export_rejection_reasons(
    connection: sqlite3.Connection,
    inputs: list[tuple[str, str, int, str]],
) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    for payroll_input_id, employee_id, _net_minor, status in inputs:
        if status != "APPROVED":
            reasons.append(
                {
                    "code": "input_not_approved",
                    "message": (
                        f"Payroll input {payroll_input_id} has status {status}; "
                        "expected APPROVED."
                    ),
                    "payroll_input_id": payroll_input_id,
                }
            )
        period_id = connection.execute(
            "SELECT period_id FROM payroll_input WHERE payroll_input_id = ?",
            (payroll_input_id,),
        ).fetchone()[0]
        reasons.extend(
            _blocking_exceptions(
                connection, payroll_input_id, employee_id, period_id
            )
        )

        source_rows = connection.execute(
            """
            SELECT source.source_id, time_entry.status
            FROM payroll_input_source AS source
            LEFT JOIN time_entry
              ON source.source_type = 'time_entry'
             AND time_entry.time_entry_id = source.source_id
            WHERE source.payroll_input_id = ?
              AND source.source_type = 'time_entry'
            ORDER BY source.source_id
            """,
            (payroll_input_id,),
        ).fetchall()
        for time_entry_id, time_status in source_rows:
            if time_status != "APPROVED":
                actual_status = time_status or "MISSING"
                reasons.append(
                    {
                        "code": "source_time_not_approved",
                        "message": (
                            f"Source time entry {time_entry_id} has status "
                            f"{actual_status}; expected APPROVED."
                        ),
                        "payroll_input_id": payroll_input_id,
                        "time_entry_id": time_entry_id,
                    }
                )
    return reasons


def create_payroll_export(
    connection: sqlite3.Connection,
    pay_group_id: str,
    period_id: str,
    *,
    requested_by: str,
) -> dict[str, Any]:
    """Create and release a complete group-period export when every gate passes."""
    requested_by = _require_text(requested_by, "requested_by")

    with _transaction(connection):
        if connection.execute(
            "SELECT 1 FROM pay_group WHERE pay_group_id = ?", (pay_group_id,)
        ).fetchone() is None:
            raise WorkflowError(404, f"Pay group {pay_group_id} was not found.")
        period = connection.execute(
            "SELECT start_date FROM pay_period WHERE period_id = ?", (period_id,)
        ).fetchone()
        if period is None:
            raise WorkflowError(404, f"Pay period {period_id} was not found.")
        existing = connection.execute(
            """
            SELECT export_id FROM payroll_export
            WHERE pay_group_id = ? AND period_id = ?
            ORDER BY export_id LIMIT 1
            """,
            (pay_group_id, period_id),
        ).fetchone()
        if existing is not None:
            raise WorkflowError(
                409,
                f"An export already exists for {pay_group_id} and {period_id}.",
                [
                    {
                        "code": "duplicate_export",
                        "message": f"Existing export: {existing[0]}.",
                        "export_id": existing[0],
                    }
                ],
            )

        inputs = connection.execute(
            """
            SELECT input.payroll_input_id, input.employee_id, input.net_minor,
                   input.status
            FROM payroll_input AS input
            JOIN employee USING (employee_id)
            WHERE employee.pay_group_id = ? AND input.period_id = ?
            ORDER BY input.payroll_input_id
            """,
            (pay_group_id, period_id),
        ).fetchall()
        if not inputs:
            raise WorkflowError(
                409,
                f"No payroll inputs exist for {pay_group_id} and {period_id}.",
                [
                    {
                        "code": "no_payroll_inputs",
                        "message": "An export requires at least one payroll input.",
                    }
                ],
            )
        reasons = _export_rejection_reasons(connection, inputs)
        if reasons:
            raise WorkflowError(
                409, "Payroll export eligibility checks failed.", reasons
            )

        year = int(period[0][:4])
        latest_export_number = connection.execute(
            """
            SELECT MAX(CAST(substr(export_id, -6) AS INTEGER))
            FROM payroll_export
            WHERE export_id LIKE ?
            """,
            (f"PEX-{year:04d}-%",),
        ).fetchone()[0]
        export_id = build_payroll_export_id(
            year, int(latest_export_number or 0) + 1
        )
        created_at = _timestamp()
        connection.execute(
            """
            INSERT INTO payroll_export
                (export_id, pay_group_id, period_id, status, line_count,
                 total_net_minor, created_at)
            VALUES (?, ?, ?, 'CREATED', 0, 0, ?)
            """,
            (export_id, pay_group_id, period_id, created_at),
        )
        _append_event(
            connection,
            entity_type="payroll_export",
            entity_id=export_id,
            from_state=None,
            to_state="CREATED",
            actor=requested_by,
            reason="Payroll export created after eligibility checks passed.",
            occurred_at=created_at,
        )
        connection.executemany(
            """
            INSERT INTO payroll_export_line
                (export_id, payroll_input_id, amount_minor)
            VALUES (?, ?, ?)
            """,
            (
                (export_id, payroll_input_id, net_minor)
                for payroll_input_id, _employee_id, net_minor, _status in inputs
            ),
        )
        total_net_minor = sum(row[2] for row in inputs)
        connection.execute(
            """
            UPDATE payroll_export
            SET status = 'RELEASED', line_count = ?, total_net_minor = ?
            WHERE export_id = ? AND status = 'CREATED'
            """,
            (len(inputs), total_net_minor, export_id),
        )
        released_at = _timestamp()
        _append_event(
            connection,
            entity_type="payroll_export",
            entity_id=export_id,
            from_state="CREATED",
            to_state="RELEASED",
            actor=requested_by,
            reason="Payroll export released.",
            occurred_at=released_at,
        )
        for payroll_input_id, _employee_id, _net_minor, _status in inputs:
            connection.execute(
                "UPDATE payroll_input SET status = 'EXPORTED' "
                "WHERE payroll_input_id = ? AND status = 'APPROVED'",
                (payroll_input_id,),
            )
            _append_event(
                connection,
                entity_type="payroll_input",
                entity_id=payroll_input_id,
                from_state="APPROVED",
                to_state="EXPORTED",
                actor=requested_by,
                reason=f"Included in payroll export {export_id}.",
                occurred_at=released_at,
            )

        lines = connection.execute(
            """
            SELECT line.payroll_input_id, input.employee_id, input.period_id,
                   line.amount_minor
            FROM payroll_export_line AS line
            JOIN payroll_input AS input USING (payroll_input_id)
            WHERE line.export_id = ?
            ORDER BY line.payroll_input_id
            """,
            (export_id,),
        ).fetchall()
    return {
        "export_id": export_id,
        "pay_group_id": pay_group_id,
        "period_id": period_id,
        "status": "RELEASED",
        "line_count": len(lines),
        "total_net_minor": total_net_minor,
        "created_at": created_at,
        "lines": [
            {
                "payroll_input_id": row[0],
                "employee_id": row[1],
                "period_id": row[2],
                "amount_minor": row[3],
            }
            for row in lines
        ],
    }


def get_payroll_export(
    connection: sqlite3.Connection, export_id: str
) -> dict[str, Any]:
    """Retrieve an export and its immutable input/employee/amount relationships."""
    export = connection.execute(
        """
        SELECT export_id, pay_group_id, period_id, status, line_count,
               total_net_minor, created_at
        FROM payroll_export WHERE export_id = ?
        """,
        (export_id,),
    ).fetchone()
    if export is None:
        raise WorkflowError(404, f"Payroll export {export_id} was not found.")
    lines = connection.execute(
        """
        SELECT line.payroll_input_id, input.employee_id, input.period_id,
               line.amount_minor
        FROM payroll_export_line AS line
        JOIN payroll_input AS input USING (payroll_input_id)
        WHERE line.export_id = ?
        ORDER BY line.payroll_input_id
        """,
        (export_id,),
    ).fetchall()
    return {
        "export_id": export[0],
        "pay_group_id": export[1],
        "period_id": export[2],
        "status": export[3],
        "line_count": export[4],
        "total_net_minor": export[5],
        "created_at": export[6],
        "lines": [
            {
                "payroll_input_id": row[0],
                "employee_id": row[1],
                "period_id": row[2],
                "amount_minor": row[3],
            }
            for row in lines
        ],
    }


__all__ = [
    "WorkflowError",
    "approve_payroll_input",
    "create_payroll_export",
    "get_payroll_export",
    "waive_exception",
]
