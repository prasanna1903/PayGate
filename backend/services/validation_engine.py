"""Run versioned payroll rules and persist auditable findings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from backend.generator.ids import (
    build_exception_id,
    build_state_event_id,
    build_validation_run_id,
)
from backend.rules import Finding, RULES


@dataclass(frozen=True)
class ValidationResult:
    """Persisted validation run and its ordered findings."""

    run_id: str
    findings: tuple[Finding, ...]
    blocked_inputs: tuple[str, ...]
    validated_inputs: tuple[str, ...]


def _next_number(conn: sqlite3.Connection, table: str, column: str) -> int:
    value = conn.execute(
        f'SELECT max(CAST(substr("{column}", 5) AS INTEGER)) FROM "{table}"'
    ).fetchone()[0]
    return int(value or 0) + 1


def _default_rule_rows() -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            rule_id,
            name,
            severity,
            int(blocking),
            json.dumps(defaults, sort_keys=True, separators=(",", ":")),
            1,
            1,
        )
        for rule_id, name, severity, blocking, defaults, _ in RULES
    )


def _load_active_rules(
    conn: sqlite3.Connection,
) -> dict[str, tuple[int, str, bool, dict[str, Any]]]:
    conn.executemany(
        """
        INSERT INTO validation_rule
            (rule_id, name, severity, blocking_flag, params_json, version, active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(rule_id) DO NOTHING
        """,
        _default_rule_rows(),
    )
    expected = {
        rule_id: (severity, blocking)
        for rule_id, _, severity, blocking, _, _ in RULES
    }
    rows = conn.execute(
        """
        SELECT rule_id, name, severity, blocking_flag, params_json, version, active
        FROM validation_rule ORDER BY rule_id
        """
    ).fetchall()
    active: dict[str, tuple[int, str, bool, dict[str, Any]]] = {}
    for row in rows:
        rule_id = row[0]
        if rule_id not in expected:
            continue
        if not row[6]:
            raise ValueError(f"Required validation rule {rule_id} is inactive")
        if (row[2], bool(row[3])) != expected[rule_id]:
            raise ValueError(
                f"Validation rule {rule_id} metadata does not match the required "
                "severity and blocking classification"
            )
        try:
            rule_params = json.loads(row[4])
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"Validation rule {rule_id} has invalid params_json") from error
        if not isinstance(rule_params, dict):
            raise ValueError(f"Validation rule {rule_id} params_json must be an object")
        active[rule_id] = (int(row[5]), row[2], bool(row[3]), rule_params)
    missing = sorted(set(expected) - set(active))
    if missing:
        raise ValueError(f"Missing active validation rules: {', '.join(missing)}")
    return active


def _effective_params(
    active: Mapping[str, tuple[int, str, bool, dict[str, Any]]],
    supplied: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    result = {rule_id: dict(value[3]) for rule_id, value in active.items()}
    if supplied is None:
        return result
    for rule_id, override in supplied.items():
        if rule_id not in result:
            raise ValueError(f"Unknown validation parameter rule: {rule_id}")
        if not isinstance(override, Mapping):
            raise ValueError(f"Parameters for {rule_id} must be a mapping")
        result[rule_id].update(override)
    return result


def _append_state_event(
    conn: sqlite3.Connection,
    event_number: int,
    *,
    entity_type: str,
    entity_id: str,
    from_state: str | None,
    to_state: str,
    reason: str,
    occurred_at: str,
) -> int:
    conn.execute(
        """
        INSERT INTO state_event
            (event_id, entity_type, entity_id, from_state, to_state, actor,
             reason, occurred_at)
        VALUES (?, ?, ?, ?, ?, 'validation_engine', ?, ?)
        """,
        (
            build_state_event_id(event_number),
            entity_type,
            entity_id,
            from_state,
            to_state,
            reason,
            occurred_at,
        ),
    )
    return event_number + 1


def _input_ids_for_finding(
    conn: sqlite3.Connection, finding: Finding
) -> set[str]:
    if finding.entity_type == "payroll_input":
        return {finding.entity_id}
    if finding.entity_type == "payroll_export_line":
        payroll_input_id = finding.evidence.get("payroll_input_id")
        if payroll_input_id:
            return {str(payroll_input_id)}
    if finding.entity_type == "payroll_export":
        row = conn.execute(
            "SELECT pay_group_id, period_id FROM payroll_export WHERE export_id = ?",
            (finding.entity_id,),
        ).fetchone()
        if row:
            return {
                item[0]
                for item in conn.execute(
                    """
                    SELECT input.payroll_input_id
                    FROM payroll_input AS input
                    JOIN employee USING (employee_id)
                    WHERE employee.pay_group_id = ? AND input.period_id = ?
                    """,
                    row,
                )
            }
    if finding.employee_id is not None:
        if finding.period_id is not None:
            rows = conn.execute(
                "SELECT payroll_input_id FROM payroll_input "
                "WHERE employee_id = ? AND period_id = ?",
                (finding.employee_id, finding.period_id),
            )
        else:
            rows = conn.execute(
                "SELECT payroll_input_id FROM payroll_input WHERE employee_id = ?",
                (finding.employee_id,),
            )
        return {row[0] for row in rows}
    if finding.period_id is not None:
        return {
            row[0]
            for row in conn.execute(
                "SELECT payroll_input_id FROM payroll_input WHERE period_id = ?",
                (finding.period_id,),
            )
        }
    return set()


def run_validation(
    conn: sqlite3.Connection,
    params: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    trigger: str = "manual",
) -> ValidationResult:
    """Execute the 12 active rules and persist run, exceptions, and state history.

    Runtime parameter overrides are keyed by rule ID, for example
    ``{"VR-005": {"threshold": 3.0}}``. Stored rule parameters are defaults.
    """
    if not isinstance(trigger, str) or not trigger.strip():
        raise ValueError("trigger must be a non-empty string")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with conn:
        active = _load_active_rules(conn)
        effective = _effective_params(active, params)
        versions = {rule_id: active[rule_id][0] for rule_id in sorted(active)}
        run_id = build_validation_run_id(
            _next_number(conn, "validation_run", "run_id")
        )
        conn.execute(
            """
            INSERT INTO validation_run
                (run_id, started_at, rule_versions_json, params_json, "trigger")
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                timestamp,
                json.dumps(versions, sort_keys=True, separators=(",", ":")),
                json.dumps(effective, sort_keys=True, separators=(",", ":")),
                trigger.strip(),
            ),
        )

        event_number = _next_number(conn, "state_event", "event_id")
        previous = conn.execute(
            """
            SELECT exception_id FROM exception
            WHERE status = 'OPEN' ORDER BY exception_id
            """
        ).fetchall()
        for (exception_id,) in previous:
            conn.execute(
                "UPDATE exception SET status = 'SUPERSEDED' "
                "WHERE exception_id = ? AND status = 'OPEN'",
                (exception_id,),
            )
            event_number = _append_state_event(
                conn,
                event_number,
                entity_type="exception",
                entity_id=exception_id,
                from_state="OPEN",
                to_state="SUPERSEDED",
                reason=f"Superseded by validation run {run_id}",
                occurred_at=timestamp,
            )

        findings: list[Finding] = []
        for rule_id, _, severity, blocking, _, function in RULES:
            rule_findings = function(conn, effective[rule_id])
            for finding in rule_findings:
                if (
                    finding.rule_id != rule_id
                    or finding.severity != severity
                    or finding.blocking != blocking
                ):
                    raise ValueError(
                        f"Rule {rule_id} returned a finding with inconsistent metadata"
                    )
            findings.extend(rule_findings)

        exception_number = _next_number(conn, "exception", "exception_id")
        for finding in findings:
            conn.execute(
                """
                INSERT INTO exception
                    (exception_id, run_id, rule_id, entity_type, entity_id,
                     employee_id, period_id, severity, status, evidence_json,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
                """,
                (
                    build_exception_id(exception_number),
                    run_id,
                    finding.rule_id,
                    finding.entity_type,
                    finding.entity_id,
                    finding.employee_id,
                    finding.period_id,
                    finding.severity,
                    json.dumps(finding.evidence, sort_keys=True, separators=(",", ":")),
                    timestamp,
                ),
            )
            event_number = _append_state_event(
                conn,
                event_number,
                entity_type="exception",
                entity_id=build_exception_id(exception_number),
                from_state=None,
                to_state="OPEN",
                reason=f"{finding.rule_id}: {finding.message}",
                occurred_at=timestamp,
            )
            exception_number += 1

        all_inputs = conn.execute(
            "SELECT payroll_input_id, employee_id, period_id, status "
            "FROM payroll_input ORDER BY payroll_input_id"
        ).fetchall()
        blocking_inputs: set[str] = set()
        for finding in findings:
            if finding.blocking:
                blocking_inputs.update(_input_ids_for_finding(conn, finding))
        blocked: list[str] = []
        validated: list[str] = []
        for payroll_input_id, employee_id, period_id, old_status in all_inputs:
            new_status = (
                "BLOCKED" if payroll_input_id in blocking_inputs else "VALIDATED"
            )
            if new_status == "BLOCKED":
                blocked.append(payroll_input_id)
            else:
                validated.append(payroll_input_id)
            if old_status != new_status:
                conn.execute(
                    "UPDATE payroll_input SET status = ? WHERE payroll_input_id = ?",
                    (new_status, payroll_input_id),
                )
                event_number = _append_state_event(
                    conn,
                    event_number,
                    entity_type="payroll_input",
                    entity_id=payroll_input_id,
                    from_state=old_status,
                    to_state=new_status,
                    reason=f"Validation run {run_id} completed",
                    occurred_at=timestamp,
                )

    return ValidationResult(
        run_id=run_id,
        findings=tuple(findings),
        blocked_inputs=tuple(blocked),
        validated_inputs=tuple(validated),
    )


__all__ = ["ValidationResult", "run_validation"]
