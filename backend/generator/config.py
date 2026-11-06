"""Environment-backed configuration for the PayGate generator."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
from collections.abc import Mapping


DEFAULT_SEED = 20261022
DEFAULT_EMPLOYEE_COUNT = 3000
DEFAULT_PAY_PERIODS = ("PP-2026-01", "PP-2026-02", "PP-2026-03")
DEFAULT_DATABASE_PATH = Path("./data/paygate.db")
DEFAULT_GROUND_TRUTH_DIR = Path("./ground_truth")
DEFAULT_ANOMALY_PLAN = (
    ("hours_exceed_period_max", 40),
    ("duplicate_allowance", 30),
    ("unapproved_time_exported", 15),
    ("leave_deduction_applied_twice", 25),
    ("totals_fail_to_reconcile", 10),
    ("missing_bank", 15),
    ("missing_tax", 15),
    ("duplicate_hours", 15),
    ("outlier_hours", 15),
    ("boundary_exact_max_hours", 10),
    ("boundary_legitimate_correction", 10),
    ("boundary_legitimate_resubmission", 10),
)

_PAY_PERIOD_PATTERN = re.compile(r"PP-(\d{4})-(\d{2})\Z")


@dataclass(frozen=True)
class GeneratorConfig:
    """Environment-backed settings shared by PayGate command-line tools."""

    seed: int
    employee_count: int
    pay_periods: tuple[str, ...]
    database_path: Path
    ground_truth_dir: Path
    anomaly_plan: tuple[tuple[str, int], ...] = DEFAULT_ANOMALY_PLAN


def _read_integer(
    environment: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
) -> int:
    value = environment.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed


def _read_pay_periods(environment: Mapping[str, str]) -> tuple[str, ...]:
    value = environment.get("PAYGATE_PAY_PERIODS")
    if value is None:
        return DEFAULT_PAY_PERIODS

    periods = tuple(period.strip() for period in value.split(","))
    if not periods:
        raise ValueError("PAYGATE_PAY_PERIODS must be a comma-separated list like PP-2026-01")
    for period in periods:
        match = _PAY_PERIOD_PATTERN.fullmatch(period)
        if match is None:
            raise ValueError(
                "PAYGATE_PAY_PERIODS must be a comma-separated list like PP-2026-01"
            )
        year, period_number = (int(value) for value in match.groups())
        if not 1 <= year <= 9999 or not 1 <= period_number <= 99:
            raise ValueError(
                "PAYGATE_PAY_PERIODS years must be 1 through 9999 and "
                "period numbers must be 1 through 99"
            )
    if len(set(periods)) != len(periods):
        raise ValueError("PAYGATE_PAY_PERIODS must not contain duplicates")
    return periods


def load_config(environment: Mapping[str, str] | None = None) -> GeneratorConfig:
    """Load configuration from environment variables, validating supplied values.

    Blueprint names SEED, DB_PATH, and GROUND_TRUTH_DIR take precedence.
    PAYGATE-prefixed aliases are retained for existing project callers.
    """
    values = os.environ if environment is None else environment
    seed = values.get("SEED", values.get("PAYGATE_SEED"))
    database_path = values.get("DB_PATH", values.get("PAYGATE_DATABASE_PATH"))
    ground_truth_dir = values.get(
        "GROUND_TRUTH_DIR", values.get("PAYGATE_GROUND_TRUTH_DIR")
    )
    return GeneratorConfig(
        seed=_read_integer(
            {"SEED": seed} if seed is not None else {},
            "SEED",
            DEFAULT_SEED,
            minimum=0,
        ),
        employee_count=_read_integer(
            values, "PAYGATE_EMPLOYEE_COUNT", DEFAULT_EMPLOYEE_COUNT, minimum=1
        ),
        pay_periods=_read_pay_periods(values),
        database_path=Path(database_path or DEFAULT_DATABASE_PATH),
        ground_truth_dir=Path(ground_truth_dir or DEFAULT_GROUND_TRUTH_DIR),
    )
