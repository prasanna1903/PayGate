"""Tests for deterministic PayGate identifier builders."""

from datetime import date, datetime

import pytest

from backend.generator.ids import (
    build_allowance_id,
    build_approval_id,
    build_deduction_id,
    build_employee_id,
    build_exception_id,
    build_leave_id,
    build_pay_group_id,
    build_pay_period_id,
    build_payroll_export_id,
    build_payroll_input_id,
    build_state_event_id,
    build_time_entry_id,
    build_validation_rule_id,
    build_validation_run_id,
)


def test_employee_id_is_zero_padded() -> None:
    assert build_employee_id(1) == "EMP-000001"


def test_employee_id_grows_past_padding_width() -> None:
    assert build_employee_id(1_000_000) == "EMP-1000000"


def test_pay_group_id_is_zero_padded() -> None:
    assert build_pay_group_id(1) == "PG-001"


def test_pay_period_id_uses_four_digit_year_and_two_digit_period() -> None:
    assert build_pay_period_id(2026, 1) == "PP-2026-01"
    assert build_pay_period_id(2026, 99) == "PP-2026-99"


def test_time_entry_id_accepts_date_and_iso_string() -> None:
    assert build_time_entry_id("EMP-000001", date(2026, 1, 5)) == (
        "TIME-EMP-000001-2026-01-05"
    )
    assert build_time_entry_id("EMP-000001", "2026-01-05") == (
        "TIME-EMP-000001-2026-01-05"
    )


@pytest.mark.parametrize(
    ("revision", "expected_suffix"),
    [(1, "-R1"), (2, "-R2")],
)
def test_time_entry_id_adds_correction_suffix(revision: int, expected_suffix: str) -> None:
    assert build_time_entry_id("EMP-000001", "2026-01-05", revision) == (
        f"TIME-EMP-000001-2026-01-05{expected_suffix}"
    )


@pytest.mark.parametrize("revision", [0, 3, -1, True, 1.5])
def test_time_entry_id_rejects_unsupported_revisions(revision) -> None:
    with pytest.raises(ValueError):
        build_time_entry_id("EMP-000001", "2026-01-05", revision)


def test_leave_id_is_zero_padded() -> None:
    assert build_leave_id(1) == "LV-000001"


def test_allowance_id_is_zero_padded() -> None:
    assert build_allowance_id(1) == "ALW-000001"


def test_deduction_id_is_zero_padded() -> None:
    assert build_deduction_id(1) == "DED-000001"


def test_payroll_input_id_uses_employee_and_month() -> None:
    assert build_payroll_input_id("EMP-000001", 2026, 1) == (
        "PIN-EMP-000001-2026-01"
    )


def test_validation_rule_id_is_zero_padded() -> None:
    assert build_validation_rule_id(1) == "VR-001"


def test_exception_id_is_zero_padded() -> None:
    assert build_exception_id(1) == "EXC-000001"


def test_approval_id_is_zero_padded() -> None:
    assert build_approval_id(1) == "APR-000001"


def test_state_event_id_is_zero_padded() -> None:
    assert build_state_event_id(1) == "EVT-000001"


def test_validation_run_id_is_zero_padded() -> None:
    assert build_validation_run_id(1) == "RUN-000001"


def test_payroll_export_id_includes_year_and_zero_padded_sequence() -> None:
    assert build_payroll_export_id(2026, 1) == "PEX-2026-000001"


@pytest.mark.parametrize(
    "builder",
    [
        build_employee_id,
        build_pay_group_id,
        build_leave_id,
        build_allowance_id,
        build_deduction_id,
        build_validation_rule_id,
        build_exception_id,
        build_approval_id,
        build_state_event_id,
        build_validation_run_id,
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_numbered_id_builders_reject_invalid_numbers(builder, value) -> None:
    with pytest.raises(ValueError):
        builder(value)


@pytest.mark.parametrize(
    ("builder", "arguments"),
    [
        (build_pay_period_id, (0, 1)),
        (build_pay_period_id, (2026, 0)),
        (build_pay_period_id, (2026, -1)),
        (build_pay_period_id, (2026, 100)),
        (build_pay_period_id, (2026, True)),
        (build_pay_period_id, (10_000, 1)),
        (build_payroll_export_id, (2026, 0)),
        (build_payroll_export_id, (0, 1)),
        (build_payroll_export_id, (2026, True)),
        (build_payroll_input_id, ("invalid", 2026, 1)),
        (build_payroll_input_id, ("EMP-000001", 2026, 0)),
        (build_payroll_input_id, ("EMP-000001", 2026, 13)),
        (build_payroll_input_id, ("EMP-000001", 2026, True)),
        (build_time_entry_id, ("invalid", "2026-01-05")),
        (build_time_entry_id, ("EMP-000001", "2026-02-30")),
        (build_time_entry_id, ("EMP-000001", "20260105")),
        (build_time_entry_id, ("EMP-000001", datetime(2026, 1, 5))),
        (build_time_entry_id, ("EMP-000001", "2026-01-05", 0)),
        (build_time_entry_id, ("EMP-000001", "2026-01-05", True)),
    ],
)
def test_composite_id_builders_reject_invalid_values(builder, arguments) -> None:
    with pytest.raises(ValueError):
        builder(*arguments)
