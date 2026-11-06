"""Persistence and lifecycle tests for the payroll validation engine."""

import inspect
import json

import pytest

from backend.services.validation_engine import run_validation
from backend.tests.validation_support import create_validation_database


@pytest.fixture
def conn(tmp_path):
    connection = create_validation_database(tmp_path / "engine.db")
    yield connection
    connection.close()


def test_engine_loads_and_executes_all_twelve_rules(conn):
    result = run_validation(conn)

    assert result.run_id == "RUN-000001"
    assert result.findings == ()
    rules = conn.execute(
        "SELECT rule_id, severity, blocking_flag, version, active "
        "FROM validation_rule ORDER BY rule_id"
    ).fetchall()
    assert len(rules) == 12
    assert [row[0] for row in rules] == [f"VR-{number:03d}" for number in range(1, 13)]
    run = conn.execute(
        "SELECT rule_versions_json, params_json, \"trigger\" "
        "FROM validation_run WHERE run_id = ?",
        (result.run_id,),
    ).fetchone()
    assert set(json.loads(run[0])) == {row[0] for row in rules}
    assert json.loads(run[1])["VR-005"]["threshold"] == 3.5
    assert run[2] == "manual"
    assert conn.execute(
        "SELECT status FROM payroll_input"
    ).fetchone()[0] == "VALIDATED"


def test_engine_persists_findings_blocks_input_and_supersedes_history(conn):
    conn.execute(
        "UPDATE employee SET tax_id = NULL WHERE employee_id = 'EMP-000001'"
    )
    first = run_validation(conn, trigger="test")
    assert {finding.rule_id for finding in first.findings} == {"VR-002"}
    assert first.blocked_inputs == ("PIN-EMP-000001-2026-01",)
    assert conn.execute(
        "SELECT status FROM payroll_input"
    ).fetchone()[0] == "BLOCKED"
    old_exception = conn.execute(
        "SELECT exception_id, evidence_json, status FROM exception"
    ).fetchone()
    assert json.loads(old_exception[1])["tax_id_missing"] is True
    assert old_exception[2] == "OPEN"

    conn.execute(
        "UPDATE employee SET tax_id = 'tax-restored' WHERE employee_id = 'EMP-000001'"
    )
    second = run_validation(conn)
    assert second.run_id == "RUN-000002"
    assert second.findings == ()
    assert second.validated_inputs == ("PIN-EMP-000001-2026-01",)
    exceptions = conn.execute(
        "SELECT exception_id, run_id, status FROM exception ORDER BY exception_id"
    ).fetchall()
    assert len(exceptions) == 1
    assert exceptions[0][0] == old_exception[0]
    assert exceptions[0][1] == first.run_id
    assert exceptions[0][2] == "SUPERSEDED"
    history = conn.execute(
        """
        SELECT from_state, to_state, reason FROM state_event
        WHERE entity_type = 'exception' AND entity_id = ?
        ORDER BY occurred_at, event_id
        """,
        (old_exception[0],),
    ).fetchall()
    assert [(row[0], row[1]) for row in history] == [
        (None, "OPEN"), ("OPEN", "SUPERSEDED")
    ]


def test_engine_uses_rule_parameter_overrides(conn):
    result = run_validation(conn, {"VR-005": {"threshold": 2.75}})
    stored = conn.execute(
        "SELECT params_json FROM validation_run WHERE run_id = ?",
        (result.run_id,),
    ).fetchone()[0]
    assert json.loads(stored)["VR-005"]["threshold"] == 2.75


def test_inactive_required_rule_fails_without_partial_run(conn):
    run_validation(conn)
    conn.execute("UPDATE validation_rule SET active = 0 WHERE rule_id = 'VR-006'")
    conn.commit()
    with pytest.raises(ValueError, match="VR-006 is inactive"):
        run_validation(conn)
    assert conn.execute("SELECT count(*) FROM validation_run").fetchone()[0] == 1


def test_engine_has_no_ground_truth_file_or_import_dependency():
    from backend.services import validation_engine

    source = inspect.getsource(validation_engine)
    assert "ground_truth" not in source
    assert "labels.csv" not in source
