"""Approval, exception-waiver, export-gate, and API workflow tests."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.services.approval_export import (
    WorkflowError,
    approve_payroll_input,
    create_payroll_export,
    get_payroll_export,
    waive_exception,
)
from backend.tests.validation_support import (
    add_employee,
    add_time_entry,
    create_validation_database,
)


INPUT_ID = "PIN-EMP-000001-2026-01"
EXCEPTION_ID = "EXC-000001"


def _create_workflow_database(path) -> sqlite3.Connection:
    connection = create_validation_database(path)
    connection.execute("DELETE FROM payroll_export_line")
    connection.execute("DELETE FROM payroll_export")
    connection.commit()
    return connection


@pytest.fixture
def conn(tmp_path):
    connection = _create_workflow_database(tmp_path / "workflow.db")
    yield connection
    connection.close()


def _add_exception(
    connection: sqlite3.Connection,
    exception_id: str = EXCEPTION_ID,
    *,
    blocking: bool = True,
    status: str = "OPEN",
    employee_id: str | None = "EMP-000001",
    period_id: str | None = "PP-2026-01",
) -> None:
    rule_id = "VR-900" if blocking else "VR-901"
    connection.execute(
        """
        INSERT INTO validation_rule
            (rule_id, name, severity, blocking_flag, params_json, version, active)
        VALUES (?, 'Synthetic test rule', 'High', ?, '{}', 1, 1)
        ON CONFLICT(rule_id) DO NOTHING
        """,
        (rule_id, int(blocking)),
    )
    connection.execute(
        """
        INSERT INTO validation_run
            (run_id, started_at, rule_versions_json, params_json, "trigger")
        VALUES ('RUN-TEST-001', '2026-01-31T12:00:00', '{}', '{}', 'test')
        ON CONFLICT(run_id) DO NOTHING
        """
    )
    connection.execute(
        """
        INSERT INTO exception
            (exception_id, run_id, rule_id, entity_type, entity_id,
             employee_id, period_id, severity, status, evidence_json, created_at)
        VALUES (?, 'RUN-TEST-001', ?, 'payroll_input', ?, ?, ?, 'High', ?, '{}',
                '2026-01-31T12:00:00')
        """,
        (
            exception_id,
            rule_id,
            INPUT_ID,
            employee_id,
            period_id,
            status,
        ),
    )
    connection.commit()


def _create_api_client(tmp_path) -> TestClient:
    database_path = tmp_path / "api.db"
    connection = _create_workflow_database(database_path)
    connection.close()
    return TestClient(create_app(database_path))


def test_approval_succeeds_and_records_approver_and_transition(conn):
    conn.execute(
        "UPDATE payroll_input SET status = 'VALIDATED' WHERE payroll_input_id = ?",
        (INPUT_ID,),
    )
    conn.commit()

    result = approve_payroll_input(
        conn,
        INPUT_ID,
        approver_id="HR-SYNTHETIC-01",
        comment="Reviewed synthetic payroll input.",
    )

    assert result["status"] == "APPROVED"
    approval = conn.execute(
        """
        SELECT target_type, target_id, approver_role, approver_id, decision, comment
        FROM approval WHERE approval_id = ?
        """,
        (result["approval_id"],),
    ).fetchone()
    assert approval == (
        "payroll_input",
        INPUT_ID,
        "HR",
        "HR-SYNTHETIC-01",
        "APPROVED",
        "Reviewed synthetic payroll input.",
    )
    assert conn.execute(
        "SELECT status FROM payroll_input WHERE payroll_input_id = ?", (INPUT_ID,)
    ).fetchone()[0] == "APPROVED"
    assert conn.execute(
        """
        SELECT from_state, to_state, actor FROM state_event
        WHERE entity_type = 'payroll_input' AND entity_id = ?
        """,
        (INPUT_ID,),
    ).fetchone() == ("VALIDATED", "APPROVED", "HR-SYNTHETIC-01")


def test_approval_missing_input_returns_not_found(conn):
    with pytest.raises(WorkflowError) as error:
        approve_payroll_input(
            conn, "PIN-MISSING", approver_id="HR-1", comment="Approved"
        )
    assert error.value.status_code == 404


def test_approval_rejects_open_blocking_exception_without_writes(conn):
    conn.execute(
        "UPDATE payroll_input SET status = 'VALIDATED' WHERE payroll_input_id = ?",
        (INPUT_ID,),
    )
    _add_exception(conn)
    before_events = conn.execute("SELECT count(*) FROM state_event").fetchone()[0]

    with pytest.raises(WorkflowError) as error:
        approve_payroll_input(
            conn, INPUT_ID, approver_id="HR-1", comment="Reviewed"
        )

    assert error.value.status_code == 409
    assert error.value.reasons[0]["exception_id"] == EXCEPTION_ID
    assert conn.execute("SELECT count(*) FROM approval").fetchone()[0] == 0
    assert conn.execute(
        "SELECT status FROM payroll_input WHERE payroll_input_id = ?", (INPUT_ID,)
    ).fetchone()[0] == "VALIDATED"
    assert conn.execute("SELECT count(*) FROM state_event").fetchone()[0] == before_events


def test_blocked_input_can_be_approved_after_its_blocker_is_waived(conn):
    conn.execute(
        "UPDATE payroll_input SET status = 'BLOCKED' WHERE payroll_input_id = ?",
        (INPUT_ID,),
    )
    _add_exception(conn)
    waive_exception(
        conn,
        EXCEPTION_ID,
        approver_id="HR-SYNTHETIC",
        comment="Waived after review.",
    )

    result = approve_payroll_input(
        conn, INPUT_ID, approver_id="HR-SYNTHETIC", comment="Approved after waiver."
    )

    assert result["status"] == "APPROVED"
    assert conn.execute(
        """
        SELECT from_state, to_state FROM state_event
        WHERE entity_type = 'payroll_input' AND entity_id = ?
        ORDER BY event_id DESC LIMIT 1
        """,
        (INPUT_ID,),
    ).fetchone() == ("BLOCKED", "APPROVED")


def test_waiving_one_blocker_does_not_allow_approval_with_another_open(conn):
    conn.execute(
        "UPDATE payroll_input SET status = 'BLOCKED' WHERE payroll_input_id = ?",
        (INPUT_ID,),
    )
    _add_exception(conn, "EXC-000001")
    _add_exception(conn, "EXC-000002")
    waive_exception(
        conn,
        "EXC-000001",
        approver_id="HR-SYNTHETIC",
        comment="Waived one exception.",
    )

    with pytest.raises(WorkflowError) as error:
        approve_payroll_input(
            conn, INPUT_ID, approver_id="HR-SYNTHETIC", comment="Approval attempt."
        )

    assert error.value.status_code == 409
    assert "EXC-000002" in {
        reason.get("exception_id") for reason in error.value.reasons
    }


def test_approval_rejects_invalid_status_transition(conn):
    conn.execute(
        "UPDATE payroll_input SET status = 'AGGREGATED' WHERE payroll_input_id = ?",
        (INPUT_ID,),
    )
    conn.commit()

    with pytest.raises(WorkflowError) as error:
        approve_payroll_input(
            conn, INPUT_ID, approver_id="HR-1", comment="Reviewed"
        )

    assert error.value.status_code == 409
    assert error.value.reasons[0]["code"] == "invalid_input_status"


def test_duplicate_approval_attempt_is_rejected(conn):
    conn.execute(
        "UPDATE payroll_input SET status = 'VALIDATED' WHERE payroll_input_id = ?",
        (INPUT_ID,),
    )
    conn.commit()
    approve_payroll_input(conn, INPUT_ID, approver_id="HR-1", comment="First")

    with pytest.raises(WorkflowError) as error:
        approve_payroll_input(conn, INPUT_ID, approver_id="HR-1", comment="Again")

    assert error.value.status_code == 409
    assert conn.execute("SELECT count(*) FROM approval").fetchone()[0] == 1


def test_valid_hr_waiver_records_approval_and_preserves_exception(conn):
    _add_exception(conn)

    result = waive_exception(
        conn,
        EXCEPTION_ID,
        approver_id="HR-SYNTHETIC-02",
        comment="Waived after synthetic HR review.",
    )

    row = conn.execute(
        "SELECT status, approval_id FROM exception WHERE exception_id = ?",
        (EXCEPTION_ID,),
    ).fetchone()
    assert row == ("WAIVED", result["approval_id"])
    assert conn.execute(
        "SELECT count(*) FROM exception WHERE exception_id = ?", (EXCEPTION_ID,)
    ).fetchone()[0] == 1
    approval = conn.execute(
        """
        SELECT target_type, target_id, approver_role, approver_id, decision, comment
        FROM approval WHERE approval_id = ?
        """,
        (result["approval_id"],),
    ).fetchone()
    assert approval == (
        "exception",
        EXCEPTION_ID,
        "HR",
        "HR-SYNTHETIC-02",
        "WAIVED",
        "Waived after synthetic HR review.",
    )
    assert conn.execute(
        """
        SELECT from_state, to_state, actor FROM state_event
        WHERE entity_type = 'exception' AND entity_id = ?
        """,
        (EXCEPTION_ID,),
    ).fetchone() == ("OPEN", "WAIVED", "HR-SYNTHETIC-02")


def test_waiver_rejects_missing_exception(conn):
    with pytest.raises(WorkflowError) as error:
        waive_exception(
            conn, "EXC-MISSING", approver_id="HR-1", comment="Waiver"
        )
    assert error.value.status_code == 404


def test_waiver_rejects_nonblocking_exception(conn):
    _add_exception(conn, blocking=False)

    with pytest.raises(WorkflowError) as error:
        waive_exception(
            conn, EXCEPTION_ID, approver_id="HR-1", comment="Waiver"
        )

    assert error.value.status_code == 409
    assert conn.execute("SELECT count(*) FROM approval").fetchone()[0] == 0


def test_waiver_rejects_invalid_exception_status(conn):
    _add_exception(conn, status="RESOLVED")

    with pytest.raises(WorkflowError) as error:
        waive_exception(
            conn, EXCEPTION_ID, approver_id="HR-1", comment="Waiver"
        )

    assert error.value.status_code == 409
    assert conn.execute(
        "SELECT status FROM exception WHERE exception_id = ?", (EXCEPTION_ID,)
    ).fetchone()[0] == "RESOLVED"


def test_waiver_requires_approver_and_nonempty_comment(conn):
    with pytest.raises(WorkflowError) as missing_approver:
        waive_exception(conn, EXCEPTION_ID, approver_id=" ", comment="Waiver")
    with pytest.raises(WorkflowError) as empty_comment:
        waive_exception(conn, EXCEPTION_ID, approver_id="HR-1", comment=" ")
    assert missing_approver.value.status_code == 400
    assert empty_comment.value.status_code == 400


def test_export_succeeds_with_correct_lines_totals_and_events(conn):
    add_employee(conn, "EMP-000002")
    conn.execute(
        """
        INSERT INTO payroll_input
            (payroll_input_id, employee_id, period_id, regular_hours, ot_hours,
             gross_minor, deductions_minor, net_minor, status, input_hash)
        VALUES ('PIN-EMP-000002-2026-01', 'EMP-000002', 'PP-2026-01',
                4, 0, 4000, 0, 4000, 'APPROVED', 'synthetic-hash')
        """
    )
    time_entry_id = add_time_entry(
        conn, "EMP-000002", "2026-01-06", status="APPROVED"
    )
    conn.execute(
        """
        INSERT INTO payroll_input_source
            (payroll_input_id, source_type, source_id)
        VALUES ('PIN-EMP-000002-2026-01', 'time_entry', ?)
        """,
        (time_entry_id,),
    )
    conn.commit()

    result = create_payroll_export(
        conn, "PG-001", "PP-2026-01", requested_by="PAYROLL-SYNTHETIC-01"
    )

    assert result["status"] == "RELEASED"
    assert result["line_count"] == 2
    assert result["total_net_minor"] == 12000
    assert result["lines"] == [
        {
            "payroll_input_id": INPUT_ID,
            "employee_id": "EMP-000001",
            "period_id": "PP-2026-01",
            "amount_minor": 8000,
        },
        {
            "payroll_input_id": "PIN-EMP-000002-2026-01",
            "employee_id": "EMP-000002",
            "period_id": "PP-2026-01",
            "amount_minor": 4000,
        },
    ]
    assert conn.execute(
        "SELECT status FROM payroll_input ORDER BY payroll_input_id"
    ).fetchall() == [("EXPORTED",), ("EXPORTED",)]
    assert conn.execute(
        """
        SELECT from_state, to_state FROM state_event
        WHERE entity_type = 'payroll_export' AND entity_id = ?
        ORDER BY event_id
        """,
        (result["export_id"],),
    ).fetchall() == [(None, "CREATED"), ("CREATED", "RELEASED")]
    assert get_payroll_export(conn, result["export_id"]) == result


def test_export_rejects_input_not_approved(conn):
    conn.execute(
        "UPDATE payroll_input SET status = 'VALIDATED' WHERE payroll_input_id = ?",
        (INPUT_ID,),
    )
    conn.commit()

    with pytest.raises(WorkflowError) as error:
        create_payroll_export(
            conn, "PG-001", "PP-2026-01", requested_by="PAYROLL-1"
        )

    assert error.value.status_code == 409
    assert "input_not_approved" in {reason["code"] for reason in error.value.reasons}


def test_export_rejects_unresolved_blocking_exception(conn):
    _add_exception(conn)

    with pytest.raises(WorkflowError) as error:
        create_payroll_export(
            conn, "PG-001", "PP-2026-01", requested_by="PAYROLL-1"
        )

    assert error.value.status_code == 409
    assert EXCEPTION_ID in {
        reason.get("exception_id") for reason in error.value.reasons
    }


def test_export_rejects_unapproved_linked_time_entry(conn):
    conn.execute(
        "UPDATE time_entry SET status = 'SUBMITTED' "
        "WHERE time_entry_id = 'TIME-EMP-000001-2026-01-05'"
    )
    conn.commit()

    with pytest.raises(WorkflowError) as error:
        create_payroll_export(
            conn, "PG-001", "PP-2026-01", requested_by="PAYROLL-1"
        )

    assert error.value.status_code == 409
    assert "source_time_not_approved" in {
        reason["code"] for reason in error.value.reasons
    }


def test_failed_export_leaves_no_partial_records_or_status_changes(conn):
    conn.execute(
        "UPDATE payroll_input SET status = 'VALIDATED' WHERE payroll_input_id = ?",
        (INPUT_ID,),
    )
    conn.execute(
        "UPDATE time_entry SET status = 'SUBMITTED' "
        "WHERE time_entry_id = 'TIME-EMP-000001-2026-01-05'"
    )
    _add_exception(conn)
    exports_before = conn.execute("SELECT count(*) FROM payroll_export").fetchone()[0]
    lines_before = conn.execute(
        "SELECT count(*) FROM payroll_export_line"
    ).fetchone()[0]
    events_before = conn.execute("SELECT count(*) FROM state_event").fetchone()[0]

    with pytest.raises(WorkflowError):
        create_payroll_export(
            conn, "PG-001", "PP-2026-01", requested_by="PAYROLL-1"
        )

    assert conn.execute("SELECT count(*) FROM payroll_export").fetchone()[0] == exports_before
    assert conn.execute(
        "SELECT count(*) FROM payroll_export_line"
    ).fetchone()[0] == lines_before
    assert conn.execute("SELECT count(*) FROM state_event").fetchone()[0] == events_before
    assert conn.execute(
        "SELECT status FROM payroll_input WHERE payroll_input_id = ?", (INPUT_ID,)
    ).fetchone()[0] == "VALIDATED"


def test_duplicate_export_is_rejected_without_duplicate_records(conn):
    first = create_payroll_export(
        conn, "PG-001", "PP-2026-01", requested_by="PAYROLL-1"
    )

    with pytest.raises(WorkflowError) as error:
        create_payroll_export(
            conn, "PG-001", "PP-2026-01", requested_by="PAYROLL-1"
        )

    assert error.value.status_code == 409
    assert error.value.reasons[0]["code"] == "duplicate_export"
    assert conn.execute("SELECT count(*) FROM payroll_export").fetchone()[0] == 1
    assert conn.execute(
        "SELECT count(*) FROM payroll_export_line WHERE export_id = ?",
        (first["export_id"],),
    ).fetchone()[0] == 1


def test_waiving_one_exception_does_not_bypass_another_blocker(conn):
    _add_exception(conn, "EXC-000001")
    _add_exception(conn, "EXC-000002")

    waive_exception(
        conn,
        "EXC-000001",
        approver_id="HR-SYNTHETIC",
        comment="Waived one exception.",
    )
    with pytest.raises(WorkflowError) as error:
        create_payroll_export(
            conn, "PG-001", "PP-2026-01", requested_by="PAYROLL-1"
        )

    assert error.value.status_code == 409
    assert "EXC-000002" in {
        reason.get("exception_id") for reason in error.value.reasons
    }


def test_export_missing_records_and_export_detail_not_found(conn):
    with pytest.raises(WorkflowError) as missing_group:
        create_payroll_export(
            conn, "PG-MISSING", "PP-2026-01", requested_by="PAYROLL-1"
        )
    with pytest.raises(WorkflowError) as missing_period:
        create_payroll_export(
            conn, "PG-001", "PP-MISSING", requested_by="PAYROLL-1"
        )
    with pytest.raises(WorkflowError) as missing_export:
        get_payroll_export(conn, "PEX-MISSING")
    assert missing_group.value.status_code == 404
    assert missing_period.value.status_code == 404
    assert missing_export.value.status_code == 404


def test_api_approval_and_export_endpoints_use_workflow_models(tmp_path):
    client = _create_api_client(tmp_path)
    with client:
        response = client.post(
            f"/payroll-inputs/{INPUT_ID}/approval",
            json={
                "approver_id": "HR-SYNTHETIC",
                "comment": "Reviewed.",
            },
        )
        assert response.status_code == 409

        with sqlite3.connect(tmp_path / "api.db") as connection:
            connection.execute(
                "UPDATE payroll_input SET status = 'VALIDATED' "
                "WHERE payroll_input_id = ?",
                (INPUT_ID,),
            )
        response = client.post(
            f"/payroll-inputs/{INPUT_ID}/approval",
            json={
                "approver_id": "HR-SYNTHETIC",
                "comment": "Reviewed.",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "APPROVED"

        export_response = client.post(
            "/exports",
            json={
                "pay_group_id": "PG-001",
                "period_id": "PP-2026-01",
                "requested_by": "PAYROLL-SYNTHETIC",
            },
        )
        assert export_response.status_code == 201
        export_id = export_response.json()["export_id"]
        details = client.get(f"/exports/{export_id}")
        assert details.status_code == 200
        assert details.json()["total_net_minor"] == 8000


def test_api_export_conflict_has_useful_rejection_reasons(tmp_path):
    client = _create_api_client(tmp_path)
    with sqlite3.connect(tmp_path / "api.db") as connection:
        connection.execute(
            "UPDATE payroll_input SET status = 'VALIDATED' "
            "WHERE payroll_input_id = ?",
            (INPUT_ID,),
        )
    with client:
        response = client.post(
            "/exports",
            json={
                "pay_group_id": "PG-001",
                "period_id": "PP-2026-01",
                "requested_by": "PAYROLL-SYNTHETIC",
            },
        )
    assert response.status_code == 409
    assert response.json()["reasons"][0]["code"] == "input_not_approved"
    assert INPUT_ID in response.json()["reasons"][0]["message"]


def test_api_waiver_validates_hr_identity_and_comment_and_records_waiver(tmp_path):
    client = _create_api_client(tmp_path)
    with sqlite3.connect(tmp_path / "api.db") as connection:
        connection.execute(
            """
            INSERT INTO validation_rule
                (rule_id, name, severity, blocking_flag, params_json, version, active)
            VALUES ('VR-900', 'Synthetic test rule', 'High', 1, '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO validation_run
                (run_id, started_at, rule_versions_json, params_json, "trigger")
            VALUES ('RUN-TEST-001', '2026-01-31T12:00:00', '{}', '{}', 'test')
            """
        )
        connection.execute(
            """
            INSERT INTO exception
                (exception_id, run_id, rule_id, entity_type, entity_id,
                 employee_id, period_id, severity, status, evidence_json, created_at)
            VALUES (?, 'RUN-TEST-001', 'VR-900', 'payroll_input', ?, ?, ?,
                    'High', 'OPEN', '{}', '2026-01-31T12:00:00')
            """,
            (EXCEPTION_ID, INPUT_ID, "EMP-000001", "PP-2026-01"),
        )
    with client:
        missing_approver = client.post(
            f"/exceptions/{EXCEPTION_ID}/waiver",
            json={"comment": "Waiver comment"},
        )
        empty_comment = client.post(
            f"/exceptions/{EXCEPTION_ID}/waiver",
            json={"approver_id": "HR-SYNTHETIC", "comment": "  "},
        )
        success = client.post(
            f"/exceptions/{EXCEPTION_ID}/waiver",
            json={
                "approver_id": "HR-SYNTHETIC",
                "comment": "HR reviewed synthetic case.",
            },
        )
    assert missing_approver.status_code == 400
    assert empty_comment.status_code == 400
    assert success.status_code == 200
    assert success.json()["status"] == "WAIVED"


def test_workflow_module_does_not_read_ground_truth():
    import inspect

    from backend.services import approval_export

    source = inspect.getsource(approval_export)
    assert "ground_truth" not in source
    assert "labels.csv" not in source
