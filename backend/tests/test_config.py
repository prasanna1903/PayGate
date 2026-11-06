"""Tests for blueprint-backed PayGate configuration defaults."""

from pathlib import Path

import pytest

from backend.generator.config import load_config


def test_configuration_uses_blueprint_defaults() -> None:
    config = load_config({})

    assert config.seed == 20261022
    assert config.employee_count == 3000
    assert config.pay_periods == (
        "PP-2026-01",
        "PP-2026-02",
        "PP-2026-03",
    )
    assert config.database_path == Path("./data/paygate.db")
    assert config.ground_truth_dir == Path("./ground_truth")


def test_blueprint_environment_names_override_legacy_aliases() -> None:
    config = load_config(
        {
            "SEED": "7",
            "PAYGATE_SEED": "8",
            "DB_PATH": "./custom/paygate.db",
            "PAYGATE_DATABASE_PATH": "./legacy/paygate.db",
            "GROUND_TRUTH_DIR": "./labels",
            "PAYGATE_GROUND_TRUTH_DIR": "./legacy-labels",
        }
    )

    assert config.seed == 7
    assert config.database_path == Path("./custom/paygate.db")
    assert config.ground_truth_dir == Path("./labels")


def test_legacy_environment_names_remain_supported() -> None:
    config = load_config(
        {
            "PAYGATE_SEED": "17",
            "PAYGATE_DATABASE_PATH": "./legacy/paygate.db",
            "PAYGATE_GROUND_TRUTH_DIR": "./legacy-labels",
        }
    )

    assert config.seed == 17
    assert config.database_path == Path("./legacy/paygate.db")
    assert config.ground_truth_dir == Path("./legacy-labels")


def test_employee_count_and_pay_period_overrides_are_applied() -> None:
    config = load_config(
        {
            "PAYGATE_EMPLOYEE_COUNT": "200",
            "PAYGATE_PAY_PERIODS": "PP-2027-01, PP-2027-02",
        }
    )

    assert config.employee_count == 200
    assert config.pay_periods == ("PP-2027-01", "PP-2027-02")


@pytest.mark.parametrize(
    "periods",
    ["PP-2026-00", "PP-2026-100", "PP-0000-01"],
)
def test_pay_period_overrides_reject_invalid_period_numbers(periods: str) -> None:
    with pytest.raises(ValueError):
        load_config({"PAYGATE_PAY_PERIODS": periods})


def test_seed_must_be_a_non_negative_integer() -> None:
    for seed in ("not-a-number", "-1"):
        with pytest.raises(ValueError):
            load_config({"SEED": seed})
