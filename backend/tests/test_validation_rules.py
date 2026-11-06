"""Positive, negative, and boundary tests for the 12 payroll rules."""

import inspect

import pytest

from backend.rules import RULES
from backend.rules import payroll as rule_module
from backend.tests.validation_support import (
    add_employee,
    add_leave,
    add_time_entry,
    create_validation_database,
)


@pytest.fixture
def conn(tmp_path):
    connection = create_validation_database(tmp_path / "rules.db")
    yield connection
    connection.close()


RULE_FUNCTIONS = {
    rule_id: function for rule_id, _, _, _, _, function in RULES
}


def test_all_twelve_rules_execute_clean_database(conn):
    assert tuple(RULE_FUNCTIONS) == tuple(f"VR-{number:03d}" for number in range(1, 13))
    for function in RULE_FUNCTIONS.values():
        assert function(conn, {}) == []


def test_vr001_missing_bank_details_and_clean_case(conn):
    assert RULE_FUNCTIONS["VR-001"](conn, {}) == []
    conn.execute(
        "UPDATE employee SET bank_account = NULL WHERE employee_id = 'EMP-000001'"
    )
    finding = RULE_FUNCTIONS["VR-001"](conn, {})[0]
    assert finding.entity_id == "EMP-000001"
    assert finding.blocking and finding.severity == "High"
    assert finding.evidence == {
        "employee_id": "EMP-000001",
        "bank_account_missing": True,
        "bank_routing_missing": False,
    }


def test_vr002_missing_tax_id_and_clean_case(conn):
    assert RULE_FUNCTIONS["VR-002"](conn, {}) == []
    conn.execute("UPDATE employee SET tax_id = NULL WHERE employee_id = 'EMP-000001'")
    finding = RULE_FUNCTIONS["VR-002"](conn, {})[0]
    assert finding.employee_id == "EMP-000001"
    assert finding.evidence["tax_id_missing"] is True
    assert finding.blocking


def test_vr003_duplicate_regular_hours_ignores_valid_revisions_and_other_types(conn):
    assert RULE_FUNCTIONS["VR-003"](conn, {}) == []
    add_time_entry(
        conn, "EMP-000001", "2026-01-05", revision="-R1",
        supersedes_id="TIME-EMP-000001-2026-01-05",
    )
    conn.execute(
        "UPDATE time_entry SET status = 'SUPERSEDED' "
        "WHERE time_entry_id = 'TIME-EMP-000001-2026-01-05'"
    )
    add_time_entry(
        conn, "EMP-000001", "2026-01-06", status="REJECTED"
    )
    add_time_entry(
        conn, "EMP-000001", "2026-01-06", revision="-R2",
        status="APPROVED", supersedes_id="TIME-EMP-000001-2026-01-06",
    )
    add_time_entry(
        conn, "EMP-000001", "2026-01-08", entry_type="OVERTIME"
    )
    assert RULE_FUNCTIONS["VR-003"](conn, {}) == []

    add_time_entry(conn, "EMP-000001", "2026-01-07")
    add_time_entry(conn, "EMP-000001", "2026-01-07", revision="-R1")
    add_time_entry(conn, "EMP-000001", "2026-01-07", revision="-R2")
    findings = RULE_FUNCTIONS["VR-003"](conn, {})
    assert len(findings) == 2
    finding = findings[0]
    assert finding.entity_id.endswith("-R1")
    assert finding.evidence["work_date"] == "2026-01-07"
    assert len(finding.evidence["duplicate_time_entry_ids"]) == 3
    assert finding.blocking

    add_time_entry(
        conn, "EMP-000001", "2026-01-08", revision="-R1",
        entry_type="OVERTIME",
    )
    findings = RULE_FUNCTIONS["VR-003"](conn, {})
    assert len(findings) == 3
    overtime_finding = next(item for item in findings if item.evidence["entry_type"] == "OVERTIME")
    assert overtime_finding.evidence["work_date"] == "2026-01-08"


def test_vr004_exact_maximum_passes_and_excess_fails(conn):
    add_time_entry(conn, "EMP-000001", "2026-01-06", hours=176)
    assert RULE_FUNCTIONS["VR-004"](conn, {}) == []
    add_time_entry(conn, "EMP-000001", "2026-01-07", hours=0.01)
    finding = RULE_FUNCTIONS["VR-004"](conn, {})[0]
    assert finding.evidence["approved_hours"] == pytest.approx(184.01)
    assert finding.evidence["maximum_hours"] == 184
    assert finding.blocking and finding.severity == "High"


def test_vr005_uses_configurable_robust_z_threshold(conn):
    add_employee(conn, "EMP-000002")
    add_employee(conn, "EMP-000003")
    add_employee(conn, "EMP-000004")
    add_time_entry(conn, "EMP-000002", "2026-01-06", hours=7)
    add_time_entry(conn, "EMP-000003", "2026-01-07", hours=9)
    add_time_entry(conn, "EMP-000004", "2026-01-08", hours=24)
    findings = RULE_FUNCTIONS["VR-005"](conn, {"threshold": 3.5})
    assert [finding.employee_id for finding in findings] == ["EMP-000004"]
    assert findings[0].severity == "Medium" and not findings[0].blocking
    assert RULE_FUNCTIONS["VR-005"](conn, {"threshold": 100}) == []
    with pytest.raises(ValueError, match="positive finite"):
        RULE_FUNCTIONS["VR-005"](conn, {"threshold": 0})


def test_vr006_duplicate_allowance_and_unique_case(conn):
    conn.executemany(
        """
        INSERT INTO allowance
            (allowance_id, employee_id, period_id, allowance_type_id,
             amount_minor, status)
        VALUES (?, 'EMP-000001', 'PP-2026-01', 'ALT-001', 500, 'APPROVED')
        """,
        [("ALW-000001",), ("ALW-000002",), ("ALW-000003",)],
    )
    findings = RULE_FUNCTIONS["VR-006"](conn, {})
    assert len(findings) == 2
    finding = findings[0]
    assert finding.entity_id == "ALW-000002"
    assert finding.evidence["duplicate_allowance_ids"] == [
        "ALW-000001", "ALW-000002", "ALW-000003"
    ]
    assert finding.blocking


def test_vr007_duplicate_leave_deduction(conn):
    add_leave(conn)
    conn.executemany(
        """
        INSERT INTO deduction
            (deduction_id, employee_id, period_id, deduction_type_id,
             amount_minor, source_leave_id, status)
        VALUES (?, 'EMP-000001', 'PP-2026-01', 'DET-001', 100,
                'LV-000001', 'APPROVED')
        """,
        [("DED-000001",), ("DED-000002",), ("DED-000003",)],
    )
    findings = RULE_FUNCTIONS["VR-007"](conn, {})
    assert len(findings) == 2
    finding = findings[0]
    assert finding.entity_id == "DED-000002"
    assert finding.evidence["source_leave_id"] == "LV-000001"
    assert finding.evidence["deduction_ids_for_leave"] == [
        "DED-000001", "DED-000002", "DED-000003"
    ]
    assert finding.blocking


def test_vr008_unapproved_time_linked_to_input(conn):
    entry_id = add_time_entry(
        conn, "EMP-000001", "2026-01-06", status="SUBMITTED"
    )
    conn.execute(
        """
        INSERT INTO payroll_input_source
            (payroll_input_id, source_type, source_id)
        VALUES ('PIN-EMP-000001-2026-01', 'time_entry', ?)
        """,
        (entry_id,),
    )
    finding = RULE_FUNCTIONS["VR-008"](conn, {})[0]
    assert finding.entity_id == entry_id
    assert finding.evidence["status"] == "SUBMITTED"
    assert finding.evidence["payroll_input_ids"] == ["PIN-EMP-000001-2026-01"]
    assert finding.evidence["export_ids"] == ["PEX-2026-000001"]
    assert finding.blocking and finding.severity == "Critical"


def test_vr009_reconciles_source_input_and_export(conn):
    assert RULE_FUNCTIONS["VR-009"](conn, {}) == []
    conn.execute(
        "UPDATE payroll_input SET gross_minor = 8001, net_minor = 8001"
    )
    findings = RULE_FUNCTIONS["VR-009"](conn, {})
    assert [finding for finding in findings if finding.entity_type == "payroll_input"]
    assert [finding for finding in findings if finding.entity_type == "payroll_export_line"]
    assert all(finding.blocking and finding.severity == "Critical" for finding in findings)


def test_vr010_eligibility_bridge_and_effective_dates(conn):
    conn.execute(
        """
        INSERT INTO allowance
            (allowance_id, employee_id, period_id, allowance_type_id,
             amount_minor, status)
        VALUES ('ALW-000001', 'EMP-000001', 'PP-2026-01', 'ALT-002', 700, 'APPROVED')
        """
    )
    finding = RULE_FUNCTIONS["VR-010"](conn, {})[0]
    assert finding.entity_id == "ALW-000001"
    assert not finding.blocking and finding.severity == "Medium"
    conn.execute(
        """
        INSERT INTO employee_allowance_eligibility
            (employee_id, allowance_type_id, effective_from, effective_to)
        VALUES ('EMP-000001', 'ALT-002', '2025-01-01', '2025-12-31')
        """
    )
    assert len(RULE_FUNCTIONS["VR-010"](conn, {})) == 1
    conn.execute(
        """
        UPDATE employee_allowance_eligibility SET effective_to = '2026-01-31'
        WHERE allowance_type_id = 'ALT-002'
        """
    )
    assert RULE_FUNCTIONS["VR-010"](conn, {}) == []


def test_vr011_approved_leave_overlap(conn):
    add_leave(conn, start_date="2026-01-05", end_date="2026-01-05")
    finding = RULE_FUNCTIONS["VR-011"](conn, {})[0]
    assert finding.entity_id == "TIME-EMP-000001-2026-01-05"
    assert finding.evidence["leave_id"] == "LV-000001"
    assert not finding.blocking


def test_vr012_effective_employment_dates_and_period(conn):
    conn.execute(
        """
        UPDATE employee SET effective_from = '2026-01-06'
        WHERE employee_id = 'EMP-000001'
        """
    )
    finding = RULE_FUNCTIONS["VR-012"](conn, {})[0]
    assert finding.entity_id == "TIME-EMP-000001-2026-01-05"
    assert "outside_employment" in finding.evidence["violations"]
    assert not finding.blocking

    add_time_entry(
        conn, "EMP-000001", "2026-02-01", period_id="PP-2026-01"
    )
    findings = RULE_FUNCTIONS["VR-012"](conn, {})
    out_of_period = next(item for item in findings if item.evidence.get("work_date") == "2026-02-01")
    assert "outside_pay_period" in out_of_period.evidence["violations"]


def test_rules_have_no_ground_truth_file_or_import_dependency():
    source = inspect.getsource(rule_module)
    assert "ground_truth" not in source
    assert "labels.csv" not in source
