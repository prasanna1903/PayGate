"""Generate deterministic leave, time, allowance, deduction, and approval rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np

from backend.generator.config import GeneratorConfig
from backend.generator.ids import (
    build_allowance_id,
    build_approval_id,
    build_deduction_id,
    build_leave_id,
    build_state_event_id,
    build_time_entry_id,
)
from backend.generator.master import MasterData


TRANSACTION_TABLES = (
    "leave_record",
    "time_entry",
    "allowance",
    "deduction",
    "approval",
    "state_event",
)


@dataclass(frozen=True)
class TransactionData:
    """Generated transaction rows and non-persisted PASS labels."""

    tables: dict[str, list[dict[str, Any]]]
    boundary_labels: list[dict[str, str]]
    leave_balances: dict[str, float]


def _weekdays(start: date, end: date) -> list[date]:
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _timestamp(day: date, hour: int = 17) -> str:
    return datetime.combine(day, time(hour=hour)).isoformat(timespec="seconds")


def _event(
    rows: list[dict[str, Any]],
    event_number: int,
    *,
    entity_type: str,
    entity_id: str,
    from_state: str | None,
    to_state: str,
    actor: str,
    reason: str,
    occurred_at: str,
) -> int:
    rows.append(
        {
            "event_id": build_state_event_id(event_number),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "from_state": from_state,
            "to_state": to_state,
            "actor": actor,
            "reason": reason,
            "occurred_at": occurred_at,
        }
    )
    return event_number + 1


def _approval(
    rows: list[dict[str, Any]],
    approval_number: int,
    *,
    target_type: str,
    target_id: str,
    approver_role: str,
    approver_id: str,
    decision: str,
    comment: str,
    decided_at: str,
) -> int:
    rows.append(
        {
            "approval_id": build_approval_id(approval_number),
            "target_type": target_type,
            "target_id": target_id,
            "approver_role": approver_role,
            "approver_id": approver_id,
            "decision": decision,
            "comment": comment,
            "decided_at": decided_at,
        }
    )
    return approval_number + 1


def build_transactions(
    master: MasterData,
    config: GeneratorConfig,
    rng: np.random.Generator,
    employee_count: int,
) -> TransactionData:
    """Build source transactions in stable order with the shared seeded RNG."""
    rows: dict[str, list[dict[str, Any]]] = {
        table: [] for table in TRANSACTION_TABLES
    }
    boundary_labels: list[dict[str, str]] = []
    approved_leave_dates: dict[tuple[str, str], set[date]] = {}
    leave_balances: dict[str, float] = {}
    approval_number = 1
    event_number = 1

    leave_count = max(1, int(round(employee_count * 0.05)))
    leave_count = min(leave_count, employee_count)
    leave_indices = np.sort(
        rng.choice(employee_count, size=leave_count, replace=False)
    )
    for leave_number, employee_index in enumerate(leave_indices, start=1):
        employee = master.employees[int(employee_index)]
        possible_periods = [
            period for period in master.periods
            if date.fromisoformat(employee["hire_date"]) <= period["_end"]
        ]
        if not possible_periods:
            continue
        period = possible_periods[int(rng.integers(len(possible_periods)))]
        period_days = _weekdays(period["_start"], period["_end"])
        eligible_days = [
            day for day in period_days
            if day >= date.fromisoformat(employee["hire_date"])
        ]
        if not eligible_days:
            continue
        start_index = int(rng.integers(len(eligible_days)))
        leave_start = eligible_days[start_index]
        leave_length = int(rng.integers(1, 4))
        leave_days = eligible_days[start_index : start_index + leave_length]
        if not leave_days:
            continue
        leave_end = leave_days[-1]
        if leave_number <= 3:
            status = "APPROVED"
            paid_flag = 0
        else:
            status = str(
                rng.choice(("APPROVED", "SUBMITTED", "REJECTED"), p=(0.90, 0.06, 0.04))
            )
            paid_flag = int(rng.random() < 0.65)
        leave_id = build_leave_id(leave_number)
        rows["leave_record"].append(
            {
                "leave_id": leave_id,
                "employee_id": employee["employee_id"],
                "period_id": period["period_id"],
                "leave_type": str(rng.choice(("ANNUAL", "SICK", "PERSONAL"))),
                "start_date": leave_start.isoformat(),
                "end_date": leave_end.isoformat(),
                "days": float(len(leave_days)),
                "paid_flag": paid_flag,
                "status": status,
            }
        )
        if status == "APPROVED":
            approved_leave_dates[
                (employee["employee_id"], period["period_id"])
            ] = set(leave_days)
            if paid_flag:
                leave_balances[employee["employee_id"]] = (
                    leave_balances.get(employee["employee_id"], 0.0) + len(leave_days)
                )
            decision_date = min(leave_end + timedelta(days=1), period["_end"])
            approval_number = _approval(
                rows["approval"],
                approval_number,
                target_type="leave_record",
                target_id=leave_id,
                approver_role="HR",
                approver_id="HR-001",
                decision="APPROVED",
                comment="Synthetic leave approval",
                decided_at=_timestamp(decision_date),
            )
        elif status == "REJECTED":
            approval_number = _approval(
                rows["approval"],
                approval_number,
                target_type="leave_record",
                target_id=leave_id,
                approver_role="HR",
                approver_id="HR-001",
                decision="REJECTED",
                comment="Synthetic leave rejection",
                decided_at=_timestamp(leave_end),
            )
        event_number = _event(
            rows["state_event"],
            event_number,
            entity_type="leave_record",
            entity_id=leave_id,
            from_state=None,
            to_state=status,
            actor="HR-001",
            reason="Generated leave record",
            occurred_at=_timestamp(leave_start),
        )

    for employee in master.employees:
        employee_id = employee["employee_id"]
        hire_date = date.fromisoformat(employee["hire_date"])
        hourly = employee["employment_type"] == "hourly"
        for period in master.periods:
            if hire_date > period["_end"]:
                continue
            workdays = [
                day for day in _weekdays(period["_start"], period["_end"])
                if day >= hire_date
            ]
            if hourly:
                leave_days = approved_leave_dates.get(
                    (employee_id, period["period_id"]), set()
                )
                selected_days = [day for day in workdays if day not in leave_days]
                for workday in selected_days:
                    base_hours = float(rng.normal(7.7, 0.55))
                    weekday_adjustment = (1.0, 0.2, 0.0, -0.1, -0.25)[workday.weekday()]
                    hours = max(5.0, base_hours + weekday_adjustment)
                    if rng.random() < 0.10:
                        hours += float(rng.lognormal(0.35, 0.45))
                    entry_type = "REGULAR"
                    event_day = workday
                    status = str(
                        rng.choice(
                            ("APPROVED", "SUBMITTED", "REJECTED", "DRAFT"),
                            p=(0.90, 0.05, 0.03, 0.02),
                        )
                    )
                    event_number, approval_number = _append_time_entry(
                        rows,
                        employee=employee,
                        period=period,
                        workday=workday,
                        hours=hours,
                        entry_type=entry_type,
                        status=status,
                        submission_seq=1,
                        supersedes_id=None,
                        revision=None,
                        event_number=event_number,
                        approval_number=approval_number,
                    )
            else:
                exception_days = workdays
                entry_count = min(2, len(exception_days))
                if not entry_count:
                    continue
                chosen = np.sort(
                    rng.choice(len(exception_days), size=entry_count, replace=False)
                )
                for index in chosen:
                    workday = exception_days[int(index)]
                    hours = float(rng.integers(1, 5))
                    status = str(
                        rng.choice(
                            ("APPROVED", "SUBMITTED", "REJECTED", "DRAFT"),
                            p=(0.90, 0.05, 0.03, 0.02),
                        )
                    )
                    event_number, approval_number = _append_time_entry(
                        rows,
                        employee=employee,
                        period=period,
                        workday=workday,
                        hours=hours,
                        entry_type="OVERTIME",
                        status=status,
                        submission_seq=1,
                        supersedes_id=None,
                        revision=None,
                        event_number=event_number,
                        approval_number=approval_number,
                    )

    _append_legitimate_revisions(
        rows,
        master,
        config,
        employee_count,
        event_number,
        approval_number,
        boundary_labels,
    )

    allowance_defaults = {
        row["allowance_type_id"]: row["default_amount_minor"]
        for row in master.allowance_types
    }
    allowance_probability = {
        "Meal Allowance": 0.68,
        "Transit Allowance": 0.58,
        "Shift Allowance": 0.52,
        "On-call Allowance": 0.32,
    }
    allowance_id_by_name = {
        row["name"]: row["allowance_type_id"] for row in master.allowance_types
    }
    allowance_uptake_by_group = {
        row["pay_group_id"]: row["allowance_uptake_factor"]
        for row in master.pay_groups
    }
    allowance_number = 0
    deduction_number = 0
    deduction_defaults = {
        row["deduction_type_id"]: row["default_amount_minor"]
        for row in master.deduction_types
    }
    for employee in master.employees:
        employee_id = employee["employee_id"]
        hire_date = date.fromisoformat(employee["hire_date"])
        uptake_factor = allowance_uptake_by_group[employee["pay_group_id"]]
        for period in master.periods:
            if hire_date > period["_end"]:
                continue
            for name in (
                "Meal Allowance",
                "Transit Allowance",
                "Shift Allowance",
                "On-call Allowance",
            ):
                allowance_type_id = allowance_id_by_name[name]
                if (
                    (employee_id, allowance_type_id) not in master.allowance_eligibility
                    or rng.random()
                    >= min(1.0, allowance_probability[name] * uptake_factor)
                ):
                    continue
                allowance_number += 1
                amount = allowance_defaults[allowance_type_id]
                amount = int(round(amount * float(rng.uniform(0.85, 1.15))))
                rows["allowance"].append(
                    {
                        "allowance_id": build_allowance_id(allowance_number),
                        "employee_id": employee_id,
                        "period_id": period["period_id"],
                        "allowance_type_id": allowance_type_id,
                        "amount_minor": amount,
                        "status": "APPROVED",
                    }
                )

            for type_row in master.deduction_types:
                deduction_type_id = type_row["deduction_type_id"]
                if (employee_id, deduction_type_id) not in master.deduction_enrollment:
                    continue
                deduction_number += 1
                default = deduction_defaults[deduction_type_id]
                amount = int(round(default * float(rng.uniform(0.9, 1.1))))
                rows["deduction"].append(
                    {
                        "deduction_id": build_deduction_id(deduction_number),
                        "employee_id": employee_id,
                        "period_id": period["period_id"],
                        "deduction_type_id": deduction_type_id,
                        "amount_minor": amount,
                        "source_leave_id": None,
                        "status": "APPROVED",
                    }
                )

    for leave in rows["leave_record"]:
        if leave["paid_flag"] or leave["status"] != "APPROVED":
            continue
        deduction_type_id = next(
            row["deduction_type_id"]
            for row in master.deduction_types
            if row["name"] == "Unpaid Leave Deduction"
        )
        deduction_number += 1
        leave_employee = next(
            row for row in master.employees if row["employee_id"] == leave["employee_id"]
        )
        daily_rate = (
            leave_employee["base_rate_minor"] * 8
            if leave_employee["employment_type"] == "hourly"
            else leave_employee["base_rate_minor"] / 160 * 8
        )
        amount = max(1, int(daily_rate * leave["days"]))
        rows["deduction"].append(
            {
                "deduction_id": build_deduction_id(deduction_number),
                "employee_id": leave["employee_id"],
                "period_id": leave["period_id"],
                "deduction_type_id": deduction_type_id,
                "amount_minor": amount,
                "source_leave_id": leave["leave_id"],
                "status": "APPROVED",
            }
        )

    return TransactionData(rows, boundary_labels, leave_balances)


def _append_time_entry(
    rows: dict[str, list[dict[str, Any]]],
    *,
    employee: dict[str, Any],
    period: dict[str, Any],
    workday: date,
    hours: float,
    entry_type: str,
    status: str,
    submission_seq: int,
    supersedes_id: str | None,
    revision: int | None,
    event_number: int,
    approval_number: int,
) -> tuple[int, int]:
    employee_id = str(employee["employee_id"])
    time_entry_id = build_time_entry_id(employee_id, workday, revision)
    submitted_at = None if status == "DRAFT" else _timestamp(workday)
    group_id = str(employee["pay_group_id"])
    approver_id = f"MGR-{group_id}"
    rows["time_entry"].append(
        {
            "time_entry_id": time_entry_id,
            "employee_id": employee_id,
            "period_id": period["period_id"],
            "work_date": workday.isoformat(),
            "hours": float(round(hours, 2)),
            "entry_type": entry_type,
            "status": status,
            "submission_seq": submission_seq,
            "supersedes_id": supersedes_id,
            "submitted_at": submitted_at,
            "approved_by": approver_id if status == "APPROVED" else None,
        }
    )
    event_number = _event(
        rows["state_event"],
        event_number,
        entity_type="time_entry",
        entity_id=time_entry_id,
        from_state=None,
        to_state="DRAFT",
        actor=employee_id,
        reason="Time entry created",
        occurred_at=_timestamp(workday, 8),
    )
    previous_state = "DRAFT"
    if status != "DRAFT":
        event_number = _event(
            rows["state_event"],
            event_number,
            entity_type="time_entry",
            entity_id=time_entry_id,
            from_state="DRAFT",
            to_state="SUBMITTED",
            actor=employee_id,
            reason="Time entry submitted",
            occurred_at=_timestamp(workday),
        )
        previous_state = "SUBMITTED"
    if status in ("APPROVED", "REJECTED"):
        event_number = _event(
            rows["state_event"],
            event_number,
            entity_type="time_entry",
            entity_id=time_entry_id,
            from_state=previous_state,
            to_state=status,
            actor=approver_id,
            reason=f"Time entry {status.lower()}",
            occurred_at=_timestamp(workday, 18),
        )
        approval_number = _approval(
            rows["approval"],
            approval_number,
            target_type="time_entry",
            target_id=time_entry_id,
            approver_role="manager",
            approver_id=approver_id,
            decision=status,
            comment=f"Synthetic time-entry {status.lower()}",
            decided_at=_timestamp(workday, 18),
        )
    return event_number, approval_number


def _append_legitimate_revisions(
    rows: dict[str, list[dict[str, Any]]],
    master: MasterData,
    config: GeneratorConfig,
    employee_count: int,
    event_number: int,
    approval_number: int,
    boundary_labels: list[dict[str, str]],
) -> None:
    plan = dict(config.anomaly_plan)
    corrections = int(
        round(plan.get("boundary_legitimate_correction", 0) * employee_count / 3000)
    )
    resubmissions = int(
        round(plan.get("boundary_legitimate_resubmission", 0) * employee_count / 3000)
    )
    entries = {row["time_entry_id"]: row for row in rows["time_entry"]}
    employees = {row["employee_id"]: row for row in master.employees}
    periods = {row["period_id"]: row for row in master.periods}
    used_dates: set[tuple[str, str]] = set()

    for category, count, source_status, revision, label_type in (
        ("correction", corrections, "APPROVED", 1, "boundary_legitimate_correction"),
        ("resubmission", resubmissions, "REJECTED", 2, "boundary_legitimate_resubmission"),
    ):
        candidates = [
            row for row in rows["time_entry"]
            if row["status"] == source_status
            and (row["employee_id"], row["work_date"]) not in used_dates
        ]
        if len(candidates) < count:
            raise ValueError(f"Not enough {source_status} entries for {category} revisions")
        for source in candidates[:count]:
            employee = employees[source["employee_id"]]
            period = periods[source["period_id"]]
            day = date.fromisoformat(source["work_date"])
            used_dates.add((source["employee_id"], source["work_date"]))
            if category == "correction":
                source["status"] = "SUPERSEDED"
                event_number = _event(
                    rows["state_event"],
                    event_number,
                    entity_type="time_entry",
                    entity_id=source["time_entry_id"],
                    from_state="APPROVED",
                    to_state="SUPERSEDED",
                    actor=f"MGR-{employee['pay_group_id']}",
                    reason="Legitimate time correction",
                    occurred_at=_timestamp(day, 19),
                )
            event_number, approval_number = _append_time_entry(
                rows,
                employee=employee,
                period=period,
                workday=day,
                hours=float(source["hours"]),
                entry_type=str(source["entry_type"]),
                status="APPROVED",
                submission_seq=2,
                supersedes_id=str(source["time_entry_id"]),
                revision=revision,
                event_number=event_number,
                approval_number=approval_number,
            )
            boundary_labels.append(
                {
                    "issue_type": label_type,
                    "entity_type": "time_entry",
                    "entity_id": build_time_entry_id(
                        source["employee_id"], day, revision
                    ),
                    "employee_id": source["employee_id"],
                    "period_id": source["period_id"],
                    "expected_rule_id": "VR-003",
                    "expected_decision": "PASS",
                    "severity": "High",
                    "injected_by": "transactions",
                    "description": (
                        f"Legitimate {category} retained its source row and "
                        "supersession link."
                    ),
                }
            )
