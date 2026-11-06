"""Validated, deterministic identifier builders for PayGate records."""

from datetime import date, datetime
import re


_EMPLOYEE_ID_PATTERN = re.compile(r"EMP-\d{6,}\Z")


def _positive_number(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _numbered_id(prefix: str, value: int, name: str, width: int) -> str:
    return f"{prefix}-{_positive_number(value, name):0{width}d}"


def _employee_id(value: str) -> str:
    if not isinstance(value, str) or not _EMPLOYEE_ID_PATTERN.fullmatch(value):
        raise ValueError("employee_id must be in the form EMP-000001")
    return value


def _year(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 9999:
        raise ValueError("year must be an integer from 1 through 9999")
    return value


def build_employee_id(employee_number: int) -> str:
    """Build an employee ID, padding employee_number to at least six digits."""
    return _numbered_id("EMP", employee_number, "employee_number", 6)


def build_pay_group_id(pay_group_number: int) -> str:
    """Build a pay-group ID, padding pay_group_number to at least three digits."""
    return _numbered_id("PG", pay_group_number, "pay_group_number", 3)


def build_pay_period_id(year: int, period_number: int) -> str:
    """Build a pay-period ID for period numbers 1 through 99."""
    if (
        isinstance(period_number, bool)
        or not isinstance(period_number, int)
        or not 1 <= period_number <= 99
    ):
        raise ValueError("period_number must be an integer from 1 through 99")
    return f"PP-{_year(year):04d}-{period_number:02d}"


def build_time_entry_id(
    employee_id: str,
    work_date: date | str,
    revision: int | None = None,
) -> str:
    """Build a time-entry ID; optional revisions are limited to 1 and 2."""
    employee = _employee_id(employee_id)
    if isinstance(work_date, datetime):
        raise ValueError("work_date must be a date or an ISO date string")
    if isinstance(work_date, date):
        iso_date = work_date.isoformat()
    elif isinstance(work_date, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", work_date):
            raise ValueError("work_date must use YYYY-MM-DD format")
        try:
            iso_date = date.fromisoformat(work_date).isoformat()
        except ValueError as error:
            raise ValueError("work_date must be a valid ISO date") from error
    else:
        raise ValueError("work_date must be a date or an ISO date string")

    if revision is None:
        suffix = ""
    elif (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision not in (1, 2)
    ):
        raise ValueError("revision must be 1 or 2")
    else:
        suffix = f"-R{revision}"
    return f"TIME-{employee}-{iso_date}{suffix}"


def build_leave_id(leave_number: int) -> str:
    """Build a leave-record ID with six-digit minimum padding."""
    return _numbered_id("LV", leave_number, "leave_number", 6)


def build_allowance_id(allowance_number: int) -> str:
    """Build an allowance ID with six-digit minimum padding."""
    return _numbered_id("ALW", allowance_number, "allowance_number", 6)


def build_deduction_id(deduction_number: int) -> str:
    """Build a deduction ID with six-digit minimum padding."""
    return _numbered_id("DED", deduction_number, "deduction_number", 6)


def build_payroll_input_id(employee_id: str, year: int, month: int) -> str:
    """Build a payroll-input ID for an employee and calendar month."""
    employee = _employee_id(employee_id)
    validated_year = _year(year)
    if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
        raise ValueError("month must be an integer from 1 through 12")
    return f"PIN-{employee}-{validated_year:04d}-{month:02d}"


def build_validation_rule_id(rule_number: int) -> str:
    """Build a validation-rule ID with three-digit minimum padding."""
    return _numbered_id("VR", rule_number, "rule_number", 3)


def build_exception_id(exception_number: int) -> str:
    """Build an exception ID with six-digit minimum padding."""
    return _numbered_id("EXC", exception_number, "exception_number", 6)


def build_approval_id(approval_number: int) -> str:
    """Build an approval ID with six-digit minimum padding."""
    return _numbered_id("APR", approval_number, "approval_number", 6)


def build_state_event_id(event_number: int) -> str:
    """Build a state-event ID with six-digit minimum padding."""
    return _numbered_id("EVT", event_number, "event_number", 6)


def build_validation_run_id(run_number: int) -> str:
    """Build a validation-run ID with six-digit minimum padding."""
    return _numbered_id("RUN", run_number, "run_number", 6)


def build_payroll_export_id(year: int, export_number: int) -> str:
    """Build a payroll-export ID from a four-digit year and sequence number."""
    return f"PEX-{_year(year):04d}-{_positive_number(export_number, 'export_number'):06d}"
