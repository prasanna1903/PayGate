"""Dashboard data and manual validation-run endpoints."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from backend.api.dashboard_models import (
    DashboardSummary,
    ExceptionItem,
    PageResponse,
    PayrollInputItem,
    ValidationRunResponse,
)
from backend.db.connection import get_connection
from backend.services.validation_engine import run_validation


def create_dashboard_router(database_path: str | Path) -> APIRouter:
    """Create dashboard routes bound to the selected SQLite database."""
    router = APIRouter()

    def database_connection() -> Iterator[sqlite3.Connection]:
        connection = get_connection(database_path)
        try:
            yield connection
        finally:
            connection.close()

    @router.get("/dashboard/summary", response_model=DashboardSummary)
    def dashboard_summary(
        connection: sqlite3.Connection = Depends(database_connection),
    ) -> dict[str, object]:
        latest_run = connection.execute(
            """
            SELECT run_id, started_at FROM validation_run
            ORDER BY started_at DESC, run_id DESC LIMIT 1
            """
        ).fetchone()
        finding_count = 0
        run_summary = None
        if latest_run is not None:
            run_id, started_at = latest_run
            finding_count = connection.execute(
                "SELECT count(*) FROM exception WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            run_summary = {
                "run_id": run_id,
                "started_at": started_at,
                "finding_count": finding_count,
                "blocked_input_count": connection.execute(
                    "SELECT count(*) FROM payroll_input WHERE status = 'BLOCKED'"
                ).fetchone()[0],
                "validated_input_count": connection.execute(
                    "SELECT count(*) FROM payroll_input WHERE status = 'VALIDATED'"
                ).fetchone()[0],
            }
        export_options = connection.execute(
            """
            SELECT calendar.pay_group_id, pay_group.name, calendar.period_id
            FROM paygroup_period_calendar AS calendar
            JOIN pay_group USING (pay_group_id)
            ORDER BY calendar.pay_group_id, calendar.period_id
            """
        ).fetchall()
        recent_exports = connection.execute(
            """
            SELECT export_id, pay_group_id, period_id, status,
                   total_net_minor, created_at
            FROM payroll_export
            ORDER BY created_at DESC, export_id DESC LIMIT 5
            """
        ).fetchall()
        return {
            "employee_count": connection.execute(
                "SELECT count(*) FROM employee"
            ).fetchone()[0],
            "payroll_input_count": connection.execute(
                "SELECT count(*) FROM payroll_input"
            ).fetchone()[0],
            "validation_finding_count": finding_count,
            "blocked_input_count": connection.execute(
                "SELECT count(*) FROM payroll_input WHERE status = 'BLOCKED'"
            ).fetchone()[0],
            "successful_export_count": connection.execute(
                "SELECT count(*) FROM payroll_export WHERE status = 'RELEASED'"
            ).fetchone()[0],
            "latest_validation_run": run_summary,
            "export_options": [
                {
                    "pay_group_id": row[0],
                    "pay_group_name": row[1],
                    "period_id": row[2],
                }
                for row in export_options
            ],
            "recent_exports": [
                {
                    "export_id": row[0],
                    "pay_group_id": row[1],
                    "period_id": row[2],
                    "status": row[3],
                    "total_net_minor": row[4],
                    "created_at": row[5],
                }
                for row in recent_exports
            ],
        }

    @router.get("/payroll-inputs", response_model=PageResponse)
    def list_payroll_inputs(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        status: str | None = None,
        query: str | None = Query(default=None, max_length=100),
        connection: sqlite3.Connection = Depends(database_connection),
    ) -> dict[str, object]:
        where: list[str] = []
        parameters: list[object] = []
        if status:
            where.append("input.status = ?")
            parameters.append(status)
        if query and query.strip():
            like = f"%{query.strip()}%"
            where.append(
                "(input.payroll_input_id LIKE ? OR input.employee_id LIKE ? "
                "OR employee.full_name LIKE ? OR input.period_id LIKE ?)"
            )
            parameters.extend((like, like, like, like))
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = connection.execute(
            f"""
            SELECT count(*) FROM payroll_input AS input
            JOIN employee USING (employee_id)
            {clause}
            """,
            parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT input.payroll_input_id, input.employee_id, employee.full_name,
                   employee.pay_group_id, input.period_id, input.regular_hours,
                   input.ot_hours, input.net_minor, input.status
            FROM payroll_input AS input
            JOIN employee USING (employee_id)
            {clause}
            ORDER BY input.period_id DESC, input.employee_id
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "payroll_input_id": row[0],
                    "employee_id": row[1],
                    "employee_name": row[2],
                    "pay_group_id": row[3],
                    "period_id": row[4],
                    "regular_hours": row[5],
                    "ot_hours": row[6],
                    "net_minor": row[7],
                    "status": row[8],
                }
                for row in rows
            ],
        }

    @router.get("/exceptions", response_model=PageResponse)
    def list_exceptions(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        status: str | None = None,
        query: str | None = Query(default=None, max_length=100),
        connection: sqlite3.Connection = Depends(database_connection),
    ) -> dict[str, object]:
        where: list[str] = []
        parameters: list[object] = []
        if status:
            where.append("exception.status = ?")
            parameters.append(status)
        if query and query.strip():
            like = f"%{query.strip()}%"
            where.append(
                "(exception.exception_id LIKE ? OR exception.rule_id LIKE ? "
                "OR exception.employee_id LIKE ? OR exception.period_id LIKE ? "
                "OR exception.entity_id LIKE ?)"
            )
            parameters.extend((like, like, like, like, like))
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = connection.execute(
            f"""
            SELECT count(*) FROM exception
            JOIN validation_rule USING (rule_id)
            {clause}
            """,
            parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT exception.exception_id, exception.run_id, exception.rule_id,
                   validation_rule.name, exception.severity,
                   validation_rule.blocking_flag, exception.status,
                   exception.entity_type, exception.entity_id,
                   exception.employee_id, exception.period_id,
                   exception.evidence_json, (
                       SELECT event.reason FROM state_event AS event
                       WHERE event.entity_type = 'exception'
                         AND event.entity_id = exception.exception_id
                         AND event.to_state = 'OPEN'
                       ORDER BY event.occurred_at DESC, event.event_id DESC
                       LIMIT 1
                   )
            FROM exception
            JOIN validation_rule USING (rule_id)
            {clause}
            ORDER BY exception.created_at DESC, exception.exception_id DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            evidence = json.loads(row[11])
            if not isinstance(evidence, dict):
                raise ValueError(f"Exception {row[0]} evidence must be a JSON object.")
            items.append(
                {
                    "exception_id": row[0],
                    "run_id": row[1],
                    "rule_id": row[2],
                    "rule_name": row[3],
                    "severity": row[4],
                    "blocking": bool(row[5]),
                    "status": row[6],
                    "entity_type": row[7],
                    "entity_id": row[8],
                    "employee_id": row[9],
                    "period_id": row[10],
                    "evidence": evidence,
                    "message": row[12],
                }
            )
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    @router.post("/validation/runs", response_model=ValidationRunResponse)
    def create_validation_run(
        connection: sqlite3.Connection = Depends(database_connection),
    ) -> dict[str, object]:
        result = run_validation(connection, trigger="manual")
        run_row = connection.execute(
            "SELECT started_at FROM validation_run WHERE run_id = ?",
            (result.run_id,),
        ).fetchone()
        exceptions = connection.execute(
            """
            SELECT exception.exception_id, exception.rule_id, validation_rule.name,
                   exception.severity, validation_rule.blocking_flag,
                   exception.status, exception.entity_type, exception.entity_id,
                   exception.employee_id, exception.period_id,
                   exception.evidence_json, (
                       SELECT event.reason FROM state_event AS event
                       WHERE event.entity_type = 'exception'
                         AND event.entity_id = exception.exception_id
                         AND event.to_state = 'OPEN'
                       ORDER BY event.occurred_at DESC, event.event_id DESC
                       LIMIT 1
                   )
            FROM exception
            JOIN validation_rule USING (rule_id)
            WHERE exception.run_id = ?
            ORDER BY exception.exception_id
            """,
            (result.run_id,),
        ).fetchall()
        return {
            "run_id": result.run_id,
            "started_at": run_row[0],
            "finding_count": len(exceptions),
            "findings": [
                {
                    "exception_id": row[0],
                    "rule_id": row[1],
                    "rule_name": row[2],
                    "severity": row[3],
                    "blocking": bool(row[4]),
                    "status": row[5],
                    "entity_type": row[6],
                    "entity_id": row[7],
                    "employee_id": row[8],
                    "period_id": row[9],
                    "evidence": json.loads(row[10]),
                    "message": row[11],
                }
                for row in exceptions
            ],
            "blocked_inputs": list(result.blocked_inputs),
            "validated_inputs": list(result.validated_inputs),
        }

    return router
