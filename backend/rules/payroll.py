"""Deterministic payroll validation rules for PayGate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import sqlite3
from collections.abc import Mapping
from typing import Any


@dataclass(frozen=True)
class Finding:
    """One validation result with stable entity references and evidence."""

    rule_id: str
    entity_type: str
    entity_id: str
    employee_id: str | None
    period_id: str | None
    severity: str
    blocking: bool
    message: str
    evidence: dict[str, Any]


RuleParams = Mapping[str, Any]


def _finding(
    rule_id: str,
    entity_type: str,
    entity_id: str,
    employee_id: str | None,
    period_id: str | None,
    severity: str,
    blocking: bool,
    message: str,
    evidence: dict[str, Any],
) -> Finding:
    return Finding(
        rule_id, entity_type, entity_id, employee_id, period_id,
        severity, blocking, message, evidence,
    )


def validate_vr001_missing_bank(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find employees missing either bank account or routing information."""
    rows = conn.execute(
        """
        SELECT employee_id, bank_account, bank_routing
        FROM employee
        WHERE bank_account IS NULL OR trim(bank_account) = ''
           OR bank_routing IS NULL OR trim(bank_routing) = ''
        ORDER BY employee_id
        """
    ).fetchall()
    return [
        _finding(
            "VR-001", "employee", row[0], row[0], None, "High", True,
            f"Employee {row[0]} is missing bank account or routing details.",
            {"employee_id": row[0], "bank_account_missing": not bool(row[1]),
             "bank_routing_missing": not bool(row[2])},
        )
        for row in rows
    ]


def validate_vr002_missing_tax_id(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find employees without a tax identifier."""
    rows = conn.execute(
        """
        SELECT employee_id FROM employee
        WHERE tax_id IS NULL OR trim(tax_id) = ''
        ORDER BY employee_id
        """
    ).fetchall()
    return [
        _finding(
            "VR-002", "employee", row[0], row[0], None, "High", True,
            f"Employee {row[0]} is missing a tax ID.",
            {"employee_id": row[0], "tax_id_missing": True},
        )
        for row in rows
    ]


def validate_vr003_duplicate_hours(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find duplicate active regular entries on an employee's work date."""
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT entry.time_entry_id, entry.employee_id, entry.period_id,
                   entry.work_date, entry.entry_type, entry.hours, entry.status,
                   row_number() OVER (
                       PARTITION BY entry.employee_id, entry.work_date,
                                    entry.entry_type
                       ORDER BY entry.time_entry_id
                   ) AS duplicate_number,
                   group_concat(entry.time_entry_id, ',') OVER (
                       PARTITION BY entry.employee_id, entry.work_date,
                                    entry.entry_type
                       ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                   ) AS group_ids
            FROM time_entry AS entry
            WHERE entry.status IN ('APPROVED', 'SUBMITTED')
              AND entry.supersedes_id IS NULL
        )
        SELECT time_entry_id, employee_id, period_id, work_date,
               entry_type, hours, status, group_ids
        FROM ranked
        WHERE duplicate_number > 1
        ORDER BY employee_id, work_date, time_entry_id
        """
    ).fetchall()
    return [
        _finding(
            "VR-003", "time_entry", row[0], row[1], row[2], "High", True,
            f"Time entries are duplicated for {row[1]} on {row[3]}.",
            {"time_entry_id": row[0], "employee_id": row[1],
             "period_id": row[2], "work_date": row[3], "entry_type": row[4],
             "hours": row[5], "status": row[6],
             "duplicate_time_entry_ids": sorted(row[7].split(","))},
        )
        for row in rows
    ]


def validate_vr004_period_max_hours(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find approved period hours strictly above the pay group's limit."""
    rows = conn.execute(
        """
        SELECT input.payroll_input_id, input.employee_id, input.period_id,
               pay_group.max_hours_per_period,
               coalesce(sum(entry.hours), 0) AS total_hours
        FROM payroll_input AS input
        JOIN employee USING (employee_id)
        JOIN pay_group USING (pay_group_id)
        LEFT JOIN time_entry AS entry
          ON entry.employee_id = input.employee_id
         AND entry.period_id = input.period_id
         AND entry.status = 'APPROVED'
        GROUP BY input.payroll_input_id, input.employee_id, input.period_id,
                 pay_group.max_hours_per_period
        HAVING total_hours > pay_group.max_hours_per_period
        ORDER BY input.payroll_input_id
        """
    ).fetchall()
    return [
        _finding(
            "VR-004", "payroll_input", row[0], row[1], row[2], "High", True,
            f"Approved hours {row[4]:g} exceed the pay-group maximum {row[3]:g}.",
            {"payroll_input_id": row[0], "employee_id": row[1],
             "period_id": row[2], "approved_hours": row[4],
             "maximum_hours": row[3]},
        )
        for row in rows
    ]


def validate_vr005_outlier_hours(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find time entries above a configurable robust peer outlier threshold."""
    threshold = float(params.get("threshold", 3.5))
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("VR-005 threshold must be a positive finite number")
    rows = conn.execute(
        """
        SELECT entry.time_entry_id, entry.employee_id, entry.period_id,
               entry.work_date, entry.entry_type, entry.hours,
               employee.pay_group_id
        FROM time_entry AS entry
        JOIN employee USING (employee_id)
        WHERE entry.status = 'APPROVED'
          AND entry.supersedes_id IS NULL
        ORDER BY employee.pay_group_id, entry.period_id, entry.entry_type,
                 entry.employee_id, entry.work_date, entry.time_entry_id
        """
    ).fetchall()
    populations: dict[tuple[str, str, str], list[float]] = {}
    for row in rows:
        key = (row[6], row[2], row[4])
        populations.setdefault(key, []).append(float(row[5]))

    findings: list[Finding] = []
    for row in rows:
        key = (row[6], row[2], row[4])
        peers = populations[key]
        if len(peers) < 3:
            continue
        ordered = sorted(peers)
        middle = len(ordered) // 2
        median = (
            ordered[middle] if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2
        )
        deviations = sorted(abs(value - median) for value in peers)
        middle = len(deviations) // 2
        mad = (
            deviations[middle] if len(deviations) % 2
            else (deviations[middle - 1] + deviations[middle]) / 2
        )
        hours = float(row[5])
        robust_z = (
            0.6744897501960817 * abs(hours - median) / mad
            if mad > 0
            else (0.0 if hours == median else math.inf)
        )
        if robust_z > threshold:
            findings.append(
                _finding(
                    "VR-005", "time_entry", row[0], row[1], row[2],
                    "Medium", False,
                    f"Time entry hours {hours:g} are an outlier for pay group {row[6]}.",
                    {"time_entry_id": row[0], "employee_id": row[1],
                     "period_id": row[2], "work_date": row[3],
                     "entry_type": row[4], "hours": hours,
                     "pay_group_id": row[6], "peer_median": median,
                     "peer_mad": mad, "robust_z_score": robust_z,
                     "threshold": threshold},
                )
            )
    return findings


def validate_vr006_duplicate_allowance(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find each extra approved allowance of one type in an employee period."""
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT allowance_id, employee_id, period_id, allowance_type_id,
                   amount_minor,
                   row_number() OVER (
                       PARTITION BY employee_id, period_id, allowance_type_id
                       ORDER BY allowance_id
                   ) AS duplicate_number,
                   group_concat(allowance_id, ',') OVER (
                       PARTITION BY employee_id, period_id, allowance_type_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                   ) AS group_ids
            FROM allowance
            WHERE status = 'APPROVED'
        )
        SELECT allowance_id, employee_id, period_id, allowance_type_id,
               amount_minor, group_ids
        FROM ranked WHERE duplicate_number > 1
        ORDER BY employee_id, period_id, allowance_type_id, allowance_id
        """
    ).fetchall()
    return [
        _finding(
            "VR-006", "allowance", row[0], row[1], row[2], "High", True,
            f"Allowance {row[0]} duplicates the same employee, type, and period.",
            {"allowance_id": row[0], "employee_id": row[1],
             "period_id": row[2], "allowance_type_id": row[3],
             "amount_minor": row[4],
             "duplicate_allowance_ids": sorted(row[5].split(","))},
        )
        for row in rows
    ]


def validate_vr007_duplicate_leave_deduction(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find each extra approved deduction attached to the same leave record."""
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT deduction_id, employee_id, period_id, source_leave_id,
                   amount_minor,
                   row_number() OVER (
                       PARTITION BY source_leave_id ORDER BY deduction_id
                   ) AS duplicate_number,
                   group_concat(deduction_id, ',') OVER (
                       PARTITION BY source_leave_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                   ) AS group_ids
            FROM deduction
            WHERE status = 'APPROVED' AND source_leave_id IS NOT NULL
        )
        SELECT deduction_id, employee_id, period_id, source_leave_id,
               amount_minor, group_ids
        FROM ranked WHERE duplicate_number > 1
        ORDER BY source_leave_id, deduction_id
        """
    ).fetchall()
    return [
        _finding(
            "VR-007", "deduction", row[0], row[1], row[2], "High", True,
            f"Leave {row[3]} has more than one approved deduction.",
            {"deduction_id": row[0], "employee_id": row[1],
             "period_id": row[2], "source_leave_id": row[3],
             "amount_minor": row[4],
             "deduction_ids_for_leave": sorted(row[5].split(","))},
        )
        for row in rows
    ]


def validate_vr008_unapproved_time_in_input(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find non-approved time linked to payroll inputs or their exports."""
    rows = conn.execute(
        """
        SELECT entry.time_entry_id, entry.employee_id, entry.period_id,
               entry.status,
               group_concat(DISTINCT linked.payroll_input_id),
               group_concat(DISTINCT line.export_id)
        FROM time_entry AS entry
        LEFT JOIN payroll_input_source AS linked
          ON linked.source_type = 'time_entry'
         AND linked.source_id = entry.time_entry_id
        LEFT JOIN payroll_export_line AS line
          ON line.payroll_input_id = linked.payroll_input_id
        WHERE entry.status != 'APPROVED'
          AND linked.payroll_input_id IS NOT NULL
        GROUP BY entry.time_entry_id, entry.employee_id, entry.period_id, entry.status
        ORDER BY entry.time_entry_id
        """
    ).fetchall()
    findings = []
    for row in rows:
        linked_inputs = sorted(filter(None, (row[4] or "").split(",")))
        export_ids = sorted(filter(None, (row[5] or "").split(",")))
        findings.append(
            _finding(
                "VR-008", "time_entry", row[0], row[1], row[2],
                "Critical", True,
                f"Time entry {row[0]} has status {row[3]} but contributes to payroll.",
                {"time_entry_id": row[0], "employee_id": row[1],
                 "period_id": row[2], "status": row[3],
                 "payroll_input_ids": linked_inputs, "export_ids": export_ids},
            )
        )
    return findings


def _input_source_totals(
    conn: sqlite3.Connection, payroll_input_id: str
) -> tuple[float, float, int, int] | None:
    row = conn.execute(
        """
        SELECT input.employee_id, input.period_id, employee.employment_type,
               employee.base_rate_minor, pay_group.ot_multiplier,
               coalesce((
                   SELECT sum(CASE WHEN entry.entry_type = 'REGULAR'
                                   THEN min(entry.hours, 8.0) ELSE 0 END)
                   FROM time_entry AS entry
                   WHERE entry.employee_id = input.employee_id
                     AND entry.period_id = input.period_id
                     AND entry.status = 'APPROVED'
               ), 0),
               coalesce((
                   SELECT sum(CASE WHEN entry.entry_type = 'REGULAR'
                                   THEN max(entry.hours - 8.0, 0)
                                   WHEN entry.entry_type = 'OVERTIME' THEN entry.hours
                                   ELSE 0 END)
                   FROM time_entry AS entry
                   WHERE entry.employee_id = input.employee_id
                     AND entry.period_id = input.period_id
                     AND entry.status = 'APPROVED'
               ), 0),
               coalesce((
                   SELECT sum(amount_minor) FROM allowance
                   WHERE employee_id = input.employee_id
                     AND period_id = input.period_id AND status = 'APPROVED'
               ), 0),
               coalesce((
                   SELECT sum(amount_minor) FROM deduction
                   WHERE employee_id = input.employee_id
                     AND period_id = input.period_id AND status = 'APPROVED'
                     AND source_leave_id IS NOT NULL
               ), 0),
               coalesce((
                   SELECT sum(amount_minor) FROM deduction
                   WHERE employee_id = input.employee_id
                     AND period_id = input.period_id AND status = 'APPROVED'
                     AND source_leave_id IS NULL
               ), 0)
        FROM payroll_input AS input
        JOIN employee USING (employee_id)
        JOIN pay_group USING (pay_group_id)
        WHERE input.payroll_input_id = ?
        """,
        (payroll_input_id,),
    ).fetchone()
    if row is None:
        return None
    regular_hours, ot_hours, allowance_minor, leave_deductions, deductions = row[5:]
    if row[2] == "hourly":
        gross = regular_hours * row[3] + ot_hours * row[3] * row[4]
    else:
        gross = row[3] + ot_hours * row[3] / 160.0 * row[4]
    gross += allowance_minor - leave_deductions
    rounded_gross = (
        math.floor(gross + 0.5) if gross >= 0 else math.ceil(gross - 0.5)
    )
    return regular_hours, ot_hours, rounded_gross, deductions


def validate_vr009_reconciliation(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Reconcile payroll inputs to approved sources and export lines to inputs."""
    findings: list[Finding] = []
    inputs = conn.execute(
        """
        SELECT payroll_input_id, employee_id, period_id, regular_hours,
               ot_hours, gross_minor, deductions_minor, net_minor
        FROM payroll_input ORDER BY payroll_input_id
        """
    ).fetchall()
    for row in inputs:
        source = _input_source_totals(conn, row[0])
        if source is None:
            continue
        regular, overtime, gross, deductions = source
        expected = {
            "regular_hours": regular,
            "ot_hours": overtime,
            "gross_minor": gross,
            "deductions_minor": deductions,
            "net_minor": gross - deductions,
        }
        actual = {
            "regular_hours": row[3],
            "ot_hours": row[4],
            "gross_minor": row[5],
            "deductions_minor": row[6],
            "net_minor": row[7],
        }
        differences = {
            key: {"expected": expected[key], "actual": actual[key]}
            for key in expected
            if (
                not math.isclose(float(expected[key]), float(actual[key]), abs_tol=0.01)
                if key.endswith("_hours")
                else expected[key] != actual[key]
            )
        }
        if differences:
            findings.append(
                _finding(
                    "VR-009", "payroll_input", row[0], row[1], row[2],
                    "Critical", True,
                    f"Payroll input {row[0]} does not reconcile to approved source records.",
                    {"payroll_input_id": row[0], "employee_id": row[1],
                     "period_id": row[2], "differences": differences},
                )
            )

    lines = conn.execute(
        """
        SELECT line.export_id, line.payroll_input_id, line.amount_minor,
               input.net_minor, input.employee_id, input.period_id
        FROM payroll_export_line AS line
        JOIN payroll_input AS input USING (payroll_input_id)
        ORDER BY line.export_id, line.payroll_input_id
        """
    ).fetchall()
    for row in lines:
        if row[2] != row[3]:
            findings.append(
                _finding(
                    "VR-009", "payroll_export_line",
                    f"{row[0]}:{row[1]}", row[4], row[5],
                    "Critical", True,
                    f"Export line for {row[1]} differs from its payroll input net.",
                    {"export_id": row[0], "payroll_input_id": row[1],
                     "export_amount_minor": row[2], "input_net_minor": row[3]},
                )
            )
    exports = conn.execute(
        """
        SELECT export_id, pay_group_id, period_id, line_count, total_net_minor,
               (SELECT count(*) FROM payroll_export_line AS line
                WHERE line.export_id = export.export_id),
               (SELECT coalesce(sum(amount_minor), 0)
                FROM payroll_export_line AS line
                WHERE line.export_id = export.export_id)
        FROM payroll_export AS export ORDER BY export_id
        """
    ).fetchall()
    for row in exports:
        if row[3] != row[5] or row[4] != row[6]:
            findings.append(
                _finding(
                    "VR-009", "payroll_export", row[0], None, row[2],
                    "Critical", True,
                    f"Export {row[0]} header does not reconcile with its lines.",
                    {"export_id": row[0], "pay_group_id": row[1],
                     "period_id": row[2], "declared_line_count": row[3],
                     "actual_line_count": row[5],
                     "declared_total_net_minor": row[4],
                     "actual_total_net_minor": row[6]},
                )
            )
    return findings


def validate_vr010_allowance_eligibility(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find approved allowances with no eligibility interval overlapping period."""
    rows = conn.execute(
        """
        SELECT allowance.allowance_id, allowance.employee_id, allowance.period_id,
               allowance.allowance_type_id, period.start_date, period.end_date
        FROM allowance
        JOIN pay_period AS period USING (period_id)
        WHERE allowance.status = 'APPROVED'
          AND NOT EXISTS (
              SELECT 1 FROM employee_allowance_eligibility AS eligibility
              WHERE eligibility.employee_id = allowance.employee_id
                AND eligibility.allowance_type_id = allowance.allowance_type_id
                AND eligibility.effective_from <= period.end_date
                AND (eligibility.effective_to IS NULL
                     OR eligibility.effective_to >= period.start_date)
          )
        ORDER BY allowance.allowance_id
        """
    ).fetchall()
    return [
        _finding(
            "VR-010", "allowance", row[0], row[1], row[2],
            "Medium", False,
            f"Allowance {row[0]} is outside the employee's eligibility dates.",
            {"allowance_id": row[0], "employee_id": row[1],
             "period_id": row[2], "allowance_type_id": row[3],
             "period_start": row[4], "period_end": row[5]},
        )
        for row in rows
    ]


def validate_vr011_time_on_approved_leave(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find approved time entries dated within approved leave intervals."""
    rows = conn.execute(
        """
        SELECT entry.time_entry_id, entry.employee_id, entry.period_id,
               entry.work_date, entry.hours, leave.leave_id,
               leave.start_date, leave.end_date
        FROM time_entry AS entry
        JOIN leave_record AS leave
          ON leave.employee_id = entry.employee_id
         AND leave.period_id = entry.period_id
         AND leave.status = 'APPROVED'
         AND entry.work_date BETWEEN leave.start_date AND leave.end_date
        WHERE entry.status = 'APPROVED'
        ORDER BY entry.time_entry_id, leave.leave_id
        """
    ).fetchall()
    return [
        _finding(
            "VR-011", "time_entry", row[0], row[1], row[2],
            "Medium", False,
            f"Approved time entry {row[0]} falls on approved leave {row[5]}.",
            {"time_entry_id": row[0], "employee_id": row[1],
             "period_id": row[2], "work_date": row[3], "hours": row[4],
             "leave_id": row[5], "leave_start": row[6], "leave_end": row[7]},
        )
        for row in rows
    ]


def validate_vr012_outside_employment_or_period(
    conn: sqlite3.Connection, params: RuleParams
) -> list[Finding]:
    """Find time and leave records outside period or effective employment dates."""
    findings: list[Finding] = []
    time_rows = conn.execute(
        """
        SELECT entry.time_entry_id, entry.employee_id, entry.period_id,
               entry.work_date, period.start_date, period.end_date,
               employee.hire_date, employee.termination_date,
               employee.effective_from, employee.effective_to
        FROM time_entry AS entry
        JOIN pay_period AS period USING (period_id)
        JOIN employee USING (employee_id)
        WHERE entry.status != 'SUPERSEDED'
        ORDER BY entry.time_entry_id
        """
    ).fetchall()
    for row in time_rows:
        work_date = date.fromisoformat(row[3])
        employment_start = max(date.fromisoformat(row[6]), date.fromisoformat(row[8]))
        employment_ends = [
            date.fromisoformat(value) for value in (row[7], row[9]) if value is not None
        ]
        employment_end = min(employment_ends) if employment_ends else None
        violations = []
        if work_date < date.fromisoformat(row[4]) or work_date > date.fromisoformat(row[5]):
            violations.append("outside_pay_period")
        if work_date < employment_start or (
            employment_end is not None and work_date > employment_end
        ):
            violations.append("outside_employment")
        if violations:
            findings.append(
                _finding(
                    "VR-012", "time_entry", row[0], row[1], row[2],
                    "Medium", False,
                    f"Time entry {row[0]} falls outside employment dates or its pay period.",
                    {"time_entry_id": row[0], "employee_id": row[1],
                     "period_id": row[2], "work_date": row[3],
                     "period_start": row[4], "period_end": row[5],
                     "hire_date": row[6], "termination_date": row[7],
                     "effective_from": row[8], "effective_to": row[9],
                     "violations": violations},
                )
            )

    leave_rows = conn.execute(
        """
        SELECT leave.leave_id, leave.employee_id, leave.period_id,
               leave.start_date, leave.end_date, period.start_date,
               period.end_date, employee.hire_date, employee.termination_date,
               employee.effective_from, employee.effective_to
        FROM leave_record AS leave
        JOIN pay_period AS period USING (period_id)
        JOIN employee USING (employee_id)
        ORDER BY leave.leave_id
        """
    ).fetchall()
    for row in leave_rows:
        start = date.fromisoformat(row[3])
        end = date.fromisoformat(row[4])
        period_start = date.fromisoformat(row[5])
        period_end = date.fromisoformat(row[6])
        employment_start = max(date.fromisoformat(row[7]), date.fromisoformat(row[9]))
        employment_ends = [
            date.fromisoformat(value) for value in (row[8], row[10]) if value is not None
        ]
        employment_end = min(employment_ends) if employment_ends else None
        violations = []
        if start < period_start or end > period_end:
            violations.append("outside_pay_period")
        if start < employment_start or (
            employment_end is not None and end > employment_end
        ):
            violations.append("outside_employment")
        if violations:
            findings.append(
                _finding(
                    "VR-012", "leave_record", row[0], row[1], row[2],
                    "Medium", False,
                    f"Leave {row[0]} falls outside employment dates or its pay period.",
                    {"leave_id": row[0], "employee_id": row[1],
                     "period_id": row[2], "start_date": row[3],
                     "end_date": row[4], "period_start": row[5],
                     "period_end": row[6], "hire_date": row[7],
                     "termination_date": row[8], "effective_from": row[9],
                     "effective_to": row[10], "violations": violations},
                )
            )
    return findings
