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

_PAY_PERIOD_PATTERN = re.compile(r"PP-\d{4}-\d{2}\Z")


@dataclass(frozen=True)
class GeneratorConfig:
    """Configuration values used by future generator modules."""

    seed: int
    employee_count: int
    pay_periods: tuple[str, ...]
    database_path: Path
    ground_truth_dir: Path


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
    if not periods or any(not _PAY_PERIOD_PATTERN.fullmatch(period) for period in periods):
        raise ValueError("PAYGATE_PAY_PERIODS must be a comma-separated list like PP-2026-01")
    if len(set(periods)) != len(periods):
        raise ValueError("PAYGATE_PAY_PERIODS must not contain duplicates")
    return periods


def load_config(environment: Mapping[str, str] | None = None) -> GeneratorConfig:
    """Load configuration from environment variables, validating supplied values.

    Supported variables are PAYGATE_SEED, PAYGATE_EMPLOYEE_COUNT,
    PAYGATE_PAY_PERIODS, PAYGATE_DATABASE_PATH, and PAYGATE_GROUND_TRUTH_DIR.
    """
    values = os.environ if environment is None else environment
    return GeneratorConfig(
        seed=_read_integer(values, "PAYGATE_SEED", DEFAULT_SEED, minimum=0),
        employee_count=_read_integer(
            values, "PAYGATE_EMPLOYEE_COUNT", DEFAULT_EMPLOYEE_COUNT, minimum=1
        ),
        pay_periods=_read_pay_periods(values),
        database_path=Path(values.get("PAYGATE_DATABASE_PATH", str(DEFAULT_DATABASE_PATH))),
        ground_truth_dir=Path(
            values.get("PAYGATE_GROUND_TRUTH_DIR", str(DEFAULT_GROUND_TRUTH_DIR))
        ),
    )
