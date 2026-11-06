"""The versioned PayGate payroll validation rule registry."""

from backend.rules.payroll import (
    Finding,
    validate_vr001_missing_bank,
    validate_vr002_missing_tax_id,
    validate_vr003_duplicate_hours,
    validate_vr004_period_max_hours,
    validate_vr005_outlier_hours,
    validate_vr006_duplicate_allowance,
    validate_vr007_duplicate_leave_deduction,
    validate_vr008_unapproved_time_in_input,
    validate_vr009_reconciliation,
    validate_vr010_allowance_eligibility,
    validate_vr011_time_on_approved_leave,
    validate_vr012_outside_employment_or_period,
)


RULES = (
    ("VR-001", "Missing bank details", "High", True, {}, validate_vr001_missing_bank),
    ("VR-002", "Missing tax ID", "High", True, {}, validate_vr002_missing_tax_id),
    ("VR-003", "Duplicate hours", "High", True, {}, validate_vr003_duplicate_hours),
    ("VR-004", "Hours exceed period maximum", "High", True, {}, validate_vr004_period_max_hours),
    ("VR-005", "Outlier hours", "Medium", False, {"threshold": 3.5}, validate_vr005_outlier_hours),
    ("VR-006", "Duplicate allowance", "High", True, {}, validate_vr006_duplicate_allowance),
    ("VR-007", "Leave deduction applied twice", "High", True, {}, validate_vr007_duplicate_leave_deduction),
    ("VR-008", "Unapproved time contributes to payroll", "Critical", True, {}, validate_vr008_unapproved_time_in_input),
    ("VR-009", "Payroll reconciliation mismatch", "Critical", True, {}, validate_vr009_reconciliation),
    ("VR-010", "Allowance eligibility", "Medium", False, {}, validate_vr010_allowance_eligibility),
    ("VR-011", "Time worked on approved leave", "Medium", False, {}, validate_vr011_time_on_approved_leave),
    ("VR-012", "Outside employment dates or pay period", "Medium", False, {}, validate_vr012_outside_employment_or_period),
)

__all__ = ["Finding", "RULES"]
