"""Build deterministic PayGate reference and employee master data."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from backend.generator.config import GeneratorConfig
from backend.generator.ids import build_employee_id, build_pay_group_id, build_pay_period_id


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_DIRECTORY = PROJECT_ROOT / "data" / "seed"
MASTER_TABLES = (
    "pay_group",
    "pay_period",
    "paygroup_period_calendar",
    "employee",
    "allowance_type",
    "deduction_type",
    "employee_allowance_eligibility",
    "employee_deduction_enrollment",
)

FIRST_NAMES = ("Ari", "Bex", "Cato", "Dara", "Eli", "Fenn", "Gio", "Hale")
LAST_NAMES = ("Ash", "Briar", "Cove", "Dale", "Elm", "Frost", "Glen", "Hart")


@dataclass(frozen=True)
class MasterData:
    """Master rows and lookups shared by transaction-generation stages."""

    tables: dict[str, list[dict[str, Any]]]
    employees: list[dict[str, Any]]
    periods: list[dict[str, Any]]
    pay_groups: list[dict[str, Any]]
    allowance_types: list[dict[str, Any]]
    deduction_types: list[dict[str, Any]]
    allowance_eligibility: set[tuple[str, str]]
    deduction_enrollment: set[tuple[str, str]]


def _read_catalog(filename: str, expected: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.read_csv(SEED_DIRECTORY / filename)
    if tuple(frame.columns) != expected or frame.empty:
        raise ValueError(f"Unexpected or empty seed catalog: {filename}")
    return frame


def _parse_periods(period_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    if len(period_ids) != 3:
        raise ValueError("Exactly three monthly pay periods are required")
    periods: list[dict[str, Any]] = []
    for period_id in period_ids:
        match = re.fullmatch(r"PP-(\d{4})-(\d{2})", period_id)
        if match is None:
            raise ValueError(f"Invalid pay period ID: {period_id}")
        year, month = (int(value) for value in match.groups())
        if build_pay_period_id(year, month) != period_id:
            raise ValueError(f"Pay period ID is not in canonical form: {period_id}")
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        periods.append(
            {
                "period_id": period_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "_start": start,
                "_end": end,
            }
        )
    for previous, current in zip(periods, periods[1:]):
        next_month = (
            previous["_start"].year + (previous["_start"].month == 12),
            previous["_start"].month % 12 + 1,
        )
        if (current["_start"].year, current["_start"].month) != next_month:
            raise ValueError("Pay periods must be three consecutive calendar months")
    return periods


def _name(rng: np.random.Generator) -> str:
    first = FIRST_NAMES[int(rng.integers(len(FIRST_NAMES)))]
    last = LAST_NAMES[int(rng.integers(len(LAST_NAMES)))]
    return f"{first} {last}"


def build_master_data(
    employee_count: int,
    config: GeneratorConfig,
    rng: np.random.Generator,
) -> MasterData:
    """Create master records using the run's shared seeded generator."""
    if employee_count < 1:
        raise ValueError("employee_count must be positive")

    group_seed = _read_catalog(
        "pay_groups.csv",
        (
            "name",
            "employment_type",
            "pay_frequency",
            "assignment_weight",
            "hourly_rate_min_minor",
            "hourly_rate_max_minor",
            "max_hours_per_period",
            "max_hours_per_day",
            "ot_multiplier",
            "cutoff_days_before_end",
            "pay_days_after_month_start",
            "allowance_uptake_factor",
        ),
    )
    allowance_seed = _read_catalog(
        "allowance_types.csv", ("name", "default_amount_minor")
    )
    deduction_seed = _read_catalog(
        "deduction_types.csv", ("name", "default_amount_minor")
    )
    if len(group_seed) != 6:
        raise ValueError("The pay-group catalog must contain exactly six groups")

    periods = _parse_periods(config.pay_periods)
    rows = {table: [] for table in MASTER_TABLES}
    pay_groups: list[dict[str, Any]] = []
    pay_group_ids: list[str] = []
    for number, item in enumerate(group_seed.itertuples(index=False), start=1):
        pay_group_id = build_pay_group_id(number)
        pay_group_ids.append(pay_group_id)
        group = {
            "pay_group_id": pay_group_id,
            "name": str(item.name),
            "employment_type": str(item.employment_type),
            "pay_frequency": str(item.pay_frequency),
            "assignment_weight": float(item.assignment_weight),
            "hourly_rate_min_minor": int(item.hourly_rate_min_minor),
            "hourly_rate_max_minor": int(item.hourly_rate_max_minor),
            "max_hours_per_period": float(item.max_hours_per_period),
            "max_hours_per_day": float(item.max_hours_per_day),
            "ot_multiplier": float(item.ot_multiplier),
            "allowance_uptake_factor": float(item.allowance_uptake_factor),
        }
        pay_groups.append(group)
        rows["pay_group"].append(
            {key: group[key] for key in (
                "pay_group_id",
                "name",
                "pay_frequency",
                "max_hours_per_period",
                "max_hours_per_day",
                "ot_multiplier",
            )}
        )

    group_indices: dict[str, np.ndarray] = {}
    for employment_type in ("hourly", "salaried"):
        indices = [
            index
            for index, group in enumerate(pay_groups)
            if group["employment_type"] == employment_type
        ]
        weights = np.array(
            [pay_groups[index]["assignment_weight"] for index in indices],
            dtype=float,
        )
        if not indices or np.any(weights < 0) or not np.isclose(weights.sum(), 1.0):
            raise ValueError(
                f"Pay-group weights for {employment_type} must sum to 1"
            )
        group_indices[employment_type] = np.array(indices, dtype=int)

    for period in periods:
        start = period["_start"]
        end = period["_end"]
        next_month = date(end.year + (end.month == 12), end.month % 12 + 1, 1)
        rows["pay_period"].append(
            {
                "period_id": period["period_id"],
                "start_date": period["start_date"],
                "end_date": period["end_date"],
                "status": "OPEN",
            }
        )
        for pay_group_id, seed_row in zip(pay_group_ids, group_seed.itertuples(index=False)):
            cutoff_date = end - timedelta(days=int(seed_row.cutoff_days_before_end))
            pay_date = next_month + timedelta(
                days=int(seed_row.pay_days_after_month_start)
            )
            rows["paygroup_period_calendar"].append(
                {
                    "pay_group_id": pay_group_id,
                    "period_id": period["period_id"],
                    "cutoff_date": cutoff_date.isoformat(),
                    "pay_date": pay_date.isoformat(),
                    "status": "OPEN",
                }
            )

    hourly_count = int(round(employee_count * 0.30))
    employment_types = np.array(
        ["hourly"] * hourly_count + ["salaried"] * (employee_count - hourly_count),
        dtype=object,
    )
    employment_types = rng.permutation(employment_types)
    first_period_start = periods[0]["_start"]
    last_period_end = periods[-1]["_end"]
    historic_start = date(2021, 1, 1)
    historic_days = (first_period_start - historic_start).days
    employees: list[dict[str, Any]] = []
    for number, employment_type in enumerate(employment_types, start=1):
        eligible_group_indices = group_indices[str(employment_type)]
        weights = [
            pay_groups[index]["assignment_weight"] for index in eligible_group_indices
        ]
        group_index = int(rng.choice(eligible_group_indices, p=weights))
        group = pay_groups[group_index]
        hourly_rate = int(
            rng.integers(
                group["hourly_rate_min_minor"],
                group["hourly_rate_max_minor"] + 1,
            )
        )
        base_rate = hourly_rate if employment_type == "hourly" else hourly_rate * 160
        if historic_days > 0 and rng.random() < 0.90:
            hire_date = historic_start + timedelta(days=int(rng.integers(historic_days)))
        else:
            span = (last_period_end - first_period_start).days + 1
            hire_date = first_period_start + timedelta(days=int(rng.integers(span)))

        employee = {
            "employee_id": build_employee_id(number),
            "full_name": _name(rng),
            "employment_type": str(employment_type),
            "pay_group_id": group["pay_group_id"],
            "hire_date": hire_date.isoformat(),
            "termination_date": None,
            "base_rate_minor": int(base_rate),
            "bank_account": f"{rng.integers(10**9, 10**12):012d}",
            "bank_routing": f"{rng.integers(10**8, 10**9):09d}",
            "tax_id": f"TX{rng.integers(10**9, 10**10)}",
            "status": "active",
            "effective_from": hire_date.isoformat(),
            "effective_to": None,
        }
        employees.append(employee)
        rows["employee"].append(employee)

    allowance_types = []
    for number, item in enumerate(allowance_seed.itertuples(index=False), start=1):
        allowance_type = {
            "allowance_type_id": f"ALT-{number:03d}",
            "name": str(item.name),
            "default_amount_minor": int(item.default_amount_minor),
            "status": "active",
        }
        allowance_types.append(allowance_type)
        rows["allowance_type"].append(allowance_type)

    deduction_types = []
    for number, item in enumerate(deduction_seed.itertuples(index=False), start=1):
        deduction_type = {
            "deduction_type_id": f"DET-{number:03d}",
            "name": str(item.name),
            "default_amount_minor": int(item.default_amount_minor),
            "status": "active",
        }
        deduction_types.append(deduction_type)
        rows["deduction_type"].append(deduction_type)

    allowance_eligibility: set[tuple[str, str]] = set()
    deduction_enrollment: set[tuple[str, str]] = set()
    allowance_id_by_name = {
        item["name"]: item["allowance_type_id"] for item in allowance_types
    }
    deduction_id_by_name = {
        item["name"]: item["deduction_type_id"] for item in deduction_types
    }
    for employee in employees:
        employee_id = employee["employee_id"]
        employee_group = pay_groups[int(employee["pay_group_id"].split("-")[1]) - 1]
        hire_date = date.fromisoformat(employee["hire_date"])
        for period in periods:
            period_start = period["_start"]
            if hire_date > period["_end"]:
                continue
            effective_from = max(hire_date, period_start).isoformat()
            tenure_days = (period_start - hire_date).days
            allowed_names = ["Meal Allowance", "Transit Allowance"]
            if employee["employment_type"] == "hourly":
                allowed_names.append("Shift Allowance")
            if (
                employee_group["name"] in ("hourly-ops", "hourly-field")
                and tenure_days >= 90
            ):
                allowed_names.append("On-call Allowance")
            for name in allowed_names:
                allowance_type_id = allowance_id_by_name[name]
                key = (employee_id, allowance_type_id)
                if key not in allowance_eligibility:
                    allowance_eligibility.add(key)
                    rows["employee_allowance_eligibility"].append(
                        {
                            "employee_id": employee_id,
                            "allowance_type_id": allowance_type_id,
                            "effective_from": effective_from,
                            "effective_to": None,
                        }
                    )

            enrolled_names = ["Statutory Deduction"]
            if tenure_days >= 90:
                enrolled_names.append("Insurance Contribution")
            if tenure_days >= 365:
                enrolled_names.append("Loan Repayment")
            for name in enrolled_names:
                deduction_type_id = deduction_id_by_name[name]
                key = (employee_id, deduction_type_id)
                if key not in deduction_enrollment:
                    deduction_enrollment.add(key)
                    rows["employee_deduction_enrollment"].append(
                        {
                            "employee_id": employee_id,
                            "deduction_type_id": deduction_type_id,
                            "effective_from": effective_from,
                            "effective_to": None,
                        }
                    )

    return MasterData(
        tables=rows,
        employees=employees,
        periods=periods,
        pay_groups=pay_groups,
        allowance_types=allowance_types,
        deduction_types=deduction_types,
        allowance_eligibility=allowance_eligibility,
        deduction_enrollment=deduction_enrollment,
    )
