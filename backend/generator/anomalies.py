"""Inject deterministic validation scenarios and write external ground-truth labels."""

from __future__ import annotations

from datetime import date, datetime, time
import sqlite3
from typing import Any

import numpy as np
import pandas as pd

from backend.generator.config import GeneratorConfig
from backend.generator.derived import aggregate_payroll_inputs
from backend.generator.export import synchronize_baseline_lines
from backend.generator.ids import (
    build_allowance_id,
    build_approval_id,
    build_deduction_id,
    build_state_event_id,
    build_time_entry_id,
)


GROUND_TRUTH_COLUMNS = (
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
)

ANOMALY_RULES = {
    "hours_exceed_period_max": ("VR-004", "High"),
    "duplicate_allowance": ("VR-006", "High"),
    "unapproved_time_exported": ("VR-008", "Critical"),
    "leave_deduction_applied_twice": ("VR-007", "High"),
    "totals_fail_to_reconcile": ("VR-009", "Critical"),
    "missing_bank": ("VR-001", "High"),
    "missing_tax": ("VR-002", "High"),
    "duplicate_hours": ("VR-003", "High"),
    "outlier_hours": ("VR-005", "Medium"),
    "boundary_exact_max_hours": ("VR-004", "High"),
}


def _next_number(connection: sqlite3.Connection, table: str, column: str) -> int:
    value = connection.execute(
        f'SELECT MAX(CAST(substr("{column}", instr("{column}", \'-\') + 1) AS INTEGER)) '
        f'FROM "{table}"'
    ).fetchone()[0]
    return int(value or 0) + 1


def _stamp(value: str, hour: int = 17) -> str:
    return datetime.combine(
        date.fromisoformat(value), time(hour=hour)
    ).isoformat(timespec="seconds")


def _scaled_count(config: GeneratorConfig, issue_type: str, employee_count: int) -> int:
    base = dict(config.anomaly_plan).get(issue_type, 0)
    if base <= 0:
        return 0
    return max(1, int(round(base * employee_count / 3000)))


def _select_inputs(
    connection: sqlite3.Connection,
    count: int,
    rng: np.random.Generator,
    used: set[tuple[str, str]],
    *,
    hourly_only: bool = False,
    require_source: str | None = None,
) -> list[tuple[str, str, str, str, float, float]]:
    condition = "AND employee.employment_type = 'hourly'" if hourly_only else ""
    source_conditions = {
        "allowance": (
            "AND EXISTS (SELECT 1 FROM allowance "
            "WHERE allowance.employee_id = input.employee_id "
            "AND allowance.period_id = input.period_id "
            "AND allowance.status = 'APPROVED')"
        ),
        "leave_deduction": (
            "AND EXISTS (SELECT 1 FROM deduction "
            "WHERE deduction.employee_id = input.employee_id "
            "AND deduction.period_id = input.period_id "
            "AND deduction.source_leave_id IS NOT NULL "
            "AND deduction.status = 'APPROVED')"
        ),
        "submitted_time": (
            "AND EXISTS (SELECT 1 FROM time_entry "
            "WHERE time_entry.employee_id = input.employee_id "
            "AND time_entry.period_id = input.period_id "
            "AND time_entry.status = 'SUBMITTED')"
        ),
        "approved_regular_time": (
            "AND EXISTS (SELECT 1 FROM time_entry "
            "WHERE time_entry.employee_id = input.employee_id "
            "AND time_entry.period_id = input.period_id "
            "AND time_entry.entry_type = 'REGULAR' "
            "AND time_entry.status = 'APPROVED')"
        ),
        "regular_hours_below_limit": (
            "AND (SELECT coalesce(sum(time_entry.hours), 0) FROM time_entry "
            "WHERE time_entry.employee_id = input.employee_id "
            "AND time_entry.period_id = input.period_id "
            "AND time_entry.entry_type = 'REGULAR' "
            "AND time_entry.status = 'APPROVED') < pay_group.max_hours_per_period "
            "AND (SELECT count(*) FROM time_entry "
            "WHERE time_entry.employee_id = input.employee_id "
            "AND time_entry.period_id = input.period_id "
            "AND time_entry.entry_type = 'REGULAR' "
            "AND time_entry.status = 'APPROVED') * pay_group.max_hours_per_day "
            ">= pay_group.max_hours_per_period"
        ),
        "capacity_above_period_max": (
            "AND (SELECT count(*) FROM time_entry "
            "WHERE time_entry.employee_id = input.employee_id "
            "AND time_entry.period_id = input.period_id "
            "AND time_entry.entry_type = 'REGULAR' "
            "AND time_entry.status = 'APPROVED') * pay_group.max_hours_per_day "
            ">= pay_group.max_hours_per_period + 1"
        ),
    }
    if require_source is not None:
        condition += " " + source_conditions[require_source]
    candidates = connection.execute(
        f"""
        SELECT input.employee_id, input.period_id, input.payroll_input_id,
               employee.pay_group_id, pay_group.max_hours_per_period,
               pay_group.max_hours_per_day
        FROM payroll_input AS input
        JOIN employee USING (employee_id)
        JOIN pay_group USING (pay_group_id)
        WHERE 1 = 1 {condition}
        ORDER BY input.employee_id, input.period_id
        """
    ).fetchall()
    candidates = [row for row in candidates if (row[0], row[1]) not in used]
    if len(candidates) < count:
        raise ValueError("Not enough distinct payroll inputs for anomaly plan")
    indices = np.sort(rng.choice(len(candidates), size=count, replace=False))
    selected = [candidates[int(index)] for index in indices]
    used.update((row[0], row[1]) for row in selected)
    return selected


def _update_hours_to_total(
    connection: sqlite3.Connection,
    employee_id: str,
    period_id: str,
    target_hours: float,
    daily_limit: float,
) -> list[str]:
    entries = connection.execute(
        """
        SELECT time_entry_id, hours
        FROM time_entry
        WHERE employee_id = ? AND period_id = ?
          AND entry_type = 'REGULAR' AND status = 'APPROVED'
        ORDER BY work_date, time_entry_id
        """,
        (employee_id, period_id),
    ).fetchall()
    if not entries:
        raise ValueError("Selected hourly input has no approved regular time entries")
    current_total = sum(float(row[1]) for row in entries)
    change = target_hours - current_total
    modified: list[str] = []
    if change >= 0:
        remaining = change
        for time_entry_id, hours in entries:
            addition = min(remaining, max(0.0, daily_limit - float(hours)))
            if addition:
                connection.execute(
                    "UPDATE time_entry SET hours = ? WHERE time_entry_id = ?",
                    (round(float(hours) + addition, 2), time_entry_id),
                )
                remaining -= addition
                modified.append(time_entry_id)
            if remaining <= 1e-8:
                break
        if remaining > 1e-8:
            raise ValueError("Pay-period target cannot fit within daily hour limits")
    else:
        remaining = -change
        for time_entry_id, hours in entries:
            reduction = min(remaining, float(hours))
            if reduction:
                connection.execute(
                    "UPDATE time_entry SET hours = ? WHERE time_entry_id = ?",
                    (round(float(hours) - reduction, 2), time_entry_id),
                )
                remaining -= reduction
                modified.append(time_entry_id)
            if remaining <= 1e-8:
                break
        if remaining > 1e-8:
            raise ValueError("Could not reduce time to requested pay-period boundary")
    actual = connection.execute(
        """
        SELECT round(sum(hours), 2) FROM time_entry
        WHERE employee_id = ? AND period_id = ?
          AND entry_type = 'REGULAR' AND status = 'APPROVED'
        """,
        (employee_id, period_id),
    ).fetchone()[0]
    if round(float(actual), 2) != round(target_hours, 2):
        raise AssertionError("Injected hours do not match the requested total")
    return modified


def _label(
    issue_type: str,
    entity_type: str,
    entity_id: str,
    employee_id: str,
    period_id: str,
    expected_decision: str,
    description: str,
) -> dict[str, str]:
    rule_id, severity = ANOMALY_RULES[issue_type]
    return {
        "issue_type": issue_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "employee_id": employee_id,
        "period_id": period_id,
        "expected_rule_id": rule_id,
        "expected_decision": expected_decision,
        "severity": severity,
        "injected_by": "backend.generator.anomalies",
        "description": description,
    }


def _inject_duplicate_allowances(
    connection: sqlite3.Connection,
    candidates: list[tuple[str, str, str, str, float, float]],
) -> list[dict[str, str]]:
    next_id = _next_number(connection, "allowance", "allowance_id")
    labels = []
    for employee_id, period_id, _, _, _, _ in candidates:
        source = connection.execute(
            "SELECT allowance_id, allowance_type_id, amount_minor FROM allowance "
            "WHERE employee_id = ? AND period_id = ? AND status = 'APPROVED' "
            "ORDER BY allowance_id LIMIT 1",
            (employee_id, period_id),
        ).fetchone()
        if source is None:
            continue
        duplicate_id = build_allowance_id(next_id)
        next_id += 1
        connection.execute(
            "INSERT INTO allowance "
            "(allowance_id, employee_id, period_id, allowance_type_id, "
            "amount_minor, status) VALUES (?, ?, ?, ?, ?, 'APPROVED')",
            (duplicate_id, employee_id, period_id, source[1], source[2]),
        )
        labels.append(
            _label(
                "duplicate_allowance",
                "allowance",
                duplicate_id,
                employee_id,
                period_id,
                "FLAG",
                f"Duplicate of allowance {source[0]} for the same employee, type, and period.",
            )
        )
    return labels


def _inject_duplicate_leave_deductions(
    connection: sqlite3.Connection,
    candidates: list[tuple[str, str, str, str, float, float]],
) -> list[dict[str, str]]:
    next_id = _next_number(connection, "deduction", "deduction_id")
    labels = []
    for employee_id, period_id, _, _, _, _ in candidates:
        source = connection.execute(
            "SELECT deduction_id, deduction_type_id, amount_minor, source_leave_id "
            "FROM deduction WHERE employee_id = ? AND period_id = ? "
            "AND source_leave_id IS NOT NULL AND status = 'APPROVED' "
            "ORDER BY deduction_id LIMIT 1",
            (employee_id, period_id),
        ).fetchone()
        if source is None:
            leave = connection.execute(
                "SELECT leave_id, start_date FROM leave_record "
                "WHERE employee_id = ? AND period_id = ? AND status = 'APPROVED' "
                "AND paid_flag = 0 ORDER BY leave_id LIMIT 1",
                (employee_id, period_id),
            ).fetchone()
            if leave is None:
                continue
            deduction_type_id = connection.execute(
                "SELECT deduction_type_id FROM deduction_type "
                "WHERE name = 'Unpaid Leave Deduction'"
            ).fetchone()[0]
            source_id = build_deduction_id(next_id)
            next_id += 1
            amount = 100
            connection.execute(
                "INSERT INTO deduction "
                "(deduction_id, employee_id, period_id, deduction_type_id, "
                "amount_minor, source_leave_id, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'APPROVED')",
                (source_id, employee_id, period_id, deduction_type_id, amount, leave[0]),
            )
            source = (source_id, deduction_type_id, amount, leave[0])
        duplicate_id = build_deduction_id(next_id)
        next_id += 1
        connection.execute(
            "INSERT INTO deduction "
            "(deduction_id, employee_id, period_id, deduction_type_id, amount_minor, "
            "source_leave_id, status) VALUES (?, ?, ?, ?, ?, ?, 'APPROVED')",
            (duplicate_id, employee_id, period_id, source[1], source[2], source[3]),
        )
        labels.append(
            _label(
                "leave_deduction_applied_twice",
                "deduction",
                duplicate_id,
                employee_id,
                period_id,
                "FLAG",
                f"Second approved deduction references leave {source[3]}; original is {source[0]}.",
            )
        )
    return labels


def _inject_duplicate_hours(
    connection: sqlite3.Connection,
    candidates: list[tuple[str, str, str, str, float, float]],
) -> list[dict[str, str]]:
    approval_number = _next_number(connection, "approval", "approval_id")
    event_number = _next_number(connection, "state_event", "event_id")
    labels = []
    for employee_id, period_id, _, pay_group_id, _, _ in candidates:
        originals = connection.execute(
            "SELECT time_entry_id, work_date, hours, entry_type "
            "FROM time_entry WHERE employee_id = ? AND period_id = ? "
            "AND status = 'APPROVED' AND entry_type = 'REGULAR' "
            "ORDER BY work_date, time_entry_id",
            (employee_id, period_id),
        ).fetchall()
        source = None
        duplicate_id = None
        for row in originals:
            for revision in (1, 2):
                proposed = build_time_entry_id(employee_id, row[1], revision)
                exists = connection.execute(
                    "SELECT 1 FROM time_entry WHERE time_entry_id = ?", (proposed,)
                ).fetchone()
                if exists is None:
                    source = row
                    duplicate_id = proposed
                    break
            if source is not None:
                break
        if source is None or duplicate_id is None:
            continue
        work_date = date.fromisoformat(source[1])
        approver_id = f"MGR-{pay_group_id}"
        connection.execute(
            "INSERT INTO time_entry "
            "(time_entry_id, employee_id, period_id, work_date, hours, entry_type, "
            "status, submission_seq, supersedes_id, submitted_at, approved_by) "
            "VALUES (?, ?, ?, ?, ?, ?, 'APPROVED', 2, NULL, ?, ?)",
            (
                duplicate_id,
                employee_id,
                period_id,
                source[1],
                source[2],
                source[3],
                _stamp(source[1]),
                approver_id,
            ),
        )
        connection.execute(
            "INSERT INTO approval "
            "(approval_id, target_type, target_id, approver_role, approver_id, "
            "decision, comment, decided_at) VALUES (?, 'time_entry', ?, 'manager', "
            "?, 'APPROVED', 'Anomalous duplicate time submission', ?)",
            (
                build_approval_id(approval_number),
                duplicate_id,
                approver_id,
                _stamp(source[1], 18),
            ),
        )
        approval_number += 1
        events = (
            (None, "DRAFT", employee_id, "Duplicate entry created", _stamp(source[1], 8)),
            ("DRAFT", "SUBMITTED", employee_id, "Duplicate entry submitted", _stamp(source[1])),
            ("SUBMITTED", "APPROVED", approver_id, "Duplicate entry approved", _stamp(source[1], 18)),
        )
        for from_state, to_state, actor, reason, occurred_at in events:
            connection.execute(
                "INSERT INTO state_event "
                "(event_id, entity_type, entity_id, from_state, to_state, actor, "
                "reason, occurred_at) VALUES (?, 'time_entry', ?, ?, ?, ?, ?, ?)",
                (
                    build_state_event_id(event_number),
                    duplicate_id,
                    from_state,
                    to_state,
                    actor,
                    reason,
                    occurred_at,
                ),
            )
            event_number += 1
        labels.append(
            _label(
                "duplicate_hours",
                "time_entry",
                duplicate_id,
                employee_id,
                period_id,
                "FLAG",
                f"Approved duplicate submission overlaps {source[0]} on {source[1]}.",
            )
        )
    return labels


def _inject_unapproved_time_links(
    connection: sqlite3.Connection,
    candidates: list[tuple[str, str, str, str, float, float]],
) -> list[dict[str, str]]:
    labels = []
    for employee_id, period_id, payroll_input_id, _, _, _ in candidates:
        entry = connection.execute(
            "SELECT time_entry_id FROM time_entry "
            "WHERE employee_id = ? AND period_id = ? AND status = 'SUBMITTED' "
            "ORDER BY time_entry_id LIMIT 1",
            (employee_id, period_id),
        ).fetchone()
        if entry is None:
            continue
        connection.execute(
            "INSERT INTO payroll_input_source "
            "(payroll_input_id, source_type, source_id) "
            "VALUES (?, 'time_entry', ?) "
            "ON CONFLICT (payroll_input_id, source_type, source_id) DO NOTHING",
            (payroll_input_id, entry[0]),
        )
        labels.append(
            _label(
                "unapproved_time_exported",
                "time_entry",
                entry[0],
                employee_id,
                period_id,
                "FLAG",
                "A submitted time entry is linked to an approved payroll input and its released export.",
            )
        )
    return labels


def _inject_missing_details(
    connection: sqlite3.Connection,
    candidates: list[tuple[str, str, str, str, float, float]],
    issue_type: str,
    column: str,
) -> list[dict[str, str]]:
    labels = []
    for employee_id, period_id, _, _, _, _ in candidates:
        if column == "bank_account":
            connection.execute(
                "UPDATE employee SET bank_account = NULL, bank_routing = NULL "
                "WHERE employee_id = ?",
                (employee_id,),
            )
        else:
            connection.execute(
                f'UPDATE employee SET "{column}" = NULL WHERE employee_id = ?',
                (employee_id,),
            )
        labels.append(
            _label(
                issue_type,
                "employee",
                employee_id,
                employee_id,
                period_id,
                "FLAG",
                f"Planned anomaly removed the employee's {column} value.",
            )
        )
    return labels


def _inject_outlier_hours(
    connection: sqlite3.Connection,
    candidates: list[tuple[str, str, str, str, float, float]],
) -> list[dict[str, str]]:
    labels = []
    for employee_id, period_id, _, _, _, daily_limit in candidates:
        row = connection.execute(
            "SELECT time_entry_id, work_date, hours FROM time_entry "
            "WHERE employee_id = ? AND period_id = ? AND status = 'APPROVED' "
            "ORDER BY time_entry_id LIMIT 1",
            (employee_id, period_id),
        ).fetchone()
        if row is None:
            continue
        new_hours = max(float(row[2]), float(daily_limit) * 1.5)
        connection.execute(
            "UPDATE time_entry SET hours = ? WHERE time_entry_id = ?",
            (round(new_hours, 2), row[0]),
        )
        labels.append(
            _label(
                "outlier_hours",
                "time_entry",
                row[0],
                employee_id,
                period_id,
                "FLAG",
                f"Planted high-hours value of {new_hours:.2f} on {row[1]}.",
            )
        )
    return labels


def _inject_reconciliation_mismatch(
    connection: sqlite3.Connection,
    candidates: list[tuple[str, str, str, str, float, float]],
) -> list[dict[str, str]]:
    labels = []
    delta_minor = 100
    for employee_id, period_id, payroll_input_id, _, _, _ in candidates:
        line = connection.execute(
            "SELECT export_id, amount_minor FROM payroll_export_line "
            "WHERE payroll_input_id = ? ORDER BY export_id LIMIT 1",
            (payroll_input_id,),
        ).fetchone()
        if line is None:
            continue
        connection.execute(
            "UPDATE payroll_export_line SET amount_minor = amount_minor + ? "
            "WHERE export_id = ? AND payroll_input_id = ?",
            (delta_minor, line[0], payroll_input_id),
        )
        connection.execute(
            "UPDATE payroll_export SET total_net_minor = total_net_minor + ? "
            "WHERE export_id = ?",
            (delta_minor, line[0]),
        )
        labels.append(
            _label(
                "totals_fail_to_reconcile",
                "payroll_export_line",
                f"{line[0]}:{payroll_input_id}",
                employee_id,
                period_id,
                "FLAG",
                f"Export line is deliberately {delta_minor} minor units above the input net.",
            )
        )
    return labels


def inject_anomalies(
    connection: sqlite3.Connection,
    config: GeneratorConfig,
    rng: np.random.Generator,
    employee_count: int,
    existing_labels: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Apply planned validation scenarios and return their external labels."""
    labels = list(existing_labels or [])
    used_inputs: set[tuple[str, str]] = set()

    def selected(
        issue_type: str,
        *,
        hourly_only: bool = False,
        require_source: str | None = None,
    ):
        return _select_inputs(
            connection,
            _scaled_count(config, issue_type, employee_count),
            rng,
            used_inputs,
            hourly_only=hourly_only,
            require_source=require_source,
        )

    exact_count = _scaled_count(
        config, "boundary_exact_max_hours", employee_count
    )
    exact_candidates = _select_inputs(
        connection,
        exact_count,
        rng,
        used_inputs,
        hourly_only=True,
        require_source="regular_hours_below_limit",
    )
    for employee_id, period_id, payroll_input_id, _, period_limit, daily_limit in exact_candidates:
        current = connection.execute(
            "SELECT coalesce(sum(hours), 0) FROM time_entry "
            "WHERE employee_id = ? AND period_id = ? AND entry_type = 'REGULAR' "
            "AND status = 'APPROVED'",
            (employee_id, period_id),
        ).fetchone()[0]
        if current > period_limit:
            raise ValueError("Cannot create exact-maximum boundary from already excessive hours")
        _update_hours_to_total(
            connection, employee_id, period_id, period_limit, daily_limit
        )
        labels.append(
            _label(
                "boundary_exact_max_hours",
                "payroll_input",
                payroll_input_id,
                employee_id,
                period_id,
                "PASS",
                f"Approved hours equal the pay-group period maximum of {period_limit:g}.",
            )
        )

    labels.extend(
        _inject_duplicate_allowances(
            connection,
            selected("duplicate_allowance", require_source="allowance"),
        )
    )
    labels.extend(
        _inject_duplicate_leave_deductions(
            connection,
            selected(
                "leave_deduction_applied_twice", require_source="leave_deduction"
            ),
        )
    )
    labels.extend(
        _inject_duplicate_hours(
            connection,
            selected(
                "duplicate_hours",
                hourly_only=True,
                require_source="approved_regular_time",
            ),
        )
    )
    labels.extend(
        _inject_outlier_hours(
            connection,
            selected(
                "outlier_hours",
                hourly_only=True,
                require_source="approved_regular_time",
            ),
        )
    )
    labels.extend(
        _inject_missing_details(connection, selected("missing_bank"), "missing_bank", "bank_account")
    )
    labels.extend(
        _inject_missing_details(connection, selected("missing_tax"), "missing_tax", "tax_id")
    )
    excess = selected(
        "hours_exceed_period_max",
        hourly_only=True,
        require_source="capacity_above_period_max",
    )
    for employee_id, period_id, payroll_input_id, _, period_limit, daily_limit in excess:
        current = connection.execute(
            "SELECT coalesce(sum(hours), 0) FROM time_entry "
            "WHERE employee_id = ? AND period_id = ? AND entry_type = 'REGULAR' "
            "AND status = 'APPROVED'",
            (employee_id, period_id),
        ).fetchone()[0]
        target = max(float(current), float(period_limit)) + 1.0
        _update_hours_to_total(
            connection, employee_id, period_id, target, daily_limit
        )
        labels.append(
            _label(
                "hours_exceed_period_max",
                "payroll_input",
                payroll_input_id,
                employee_id,
                period_id,
                "FLAG",
                f"Approved hours are deliberately above the {period_limit:g}-hour group limit.",
            )
        )

    aggregate_payroll_inputs(connection)
    synchronize_baseline_lines(connection)
    labels.extend(
        _inject_unapproved_time_links(
            connection,
            selected(
                "unapproved_time_exported", require_source="submitted_time"
            ),
        )
    )
    labels.extend(
        _inject_reconciliation_mismatch(
            connection, selected("totals_fail_to_reconcile")
        )
    )
    labels = sorted(
        labels,
        key=lambda row: (
            row["issue_type"],
            row["period_id"],
            row["employee_id"],
            row["entity_id"],
        ),
    )
    for number, label in enumerate(labels, start=1):
        label["gt_id"] = f"GT-{number:06d}"
    return labels


def write_ground_truth(labels: list[dict[str, str]], path: str) -> None:
    """Write labelled scenarios to a CSV outside the operational database."""
    ordered = [{column: label[column] for column in GROUND_TRUTH_COLUMNS} for label in labels]
    pd.DataFrame.from_records(ordered, columns=GROUND_TRUTH_COLUMNS).to_csv(
        path, index=False, lineterminator="\n"
    )
