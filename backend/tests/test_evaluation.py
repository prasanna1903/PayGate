"""Ground-truth evaluation metrics, persistence boundaries, and API tests."""

import csv
import hashlib
import inspect
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.evaluation.scorecard import (
    EvaluationError,
    GROUND_TRUTH_COLUMNS,
    evaluate_dataset,
    evaluate_findings,
)


def _label(
    *,
    gt_id: str = "GT-000001",
    issue_type: str = "missing_bank",
    rule_id: str = "VR-001",
    entity_type: str = "employee",
    entity_id: str = "EMP-000001",
    employee_id: str = "EMP-000001",
    period_id: str = "PP-2026-01",
    decision: str = "FLAG",
    severity: str = "High",
) -> dict[str, str]:
    return {
        "gt_id": gt_id,
        "issue_type": issue_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "employee_id": employee_id,
        "period_id": period_id,
        "expected_rule_id": rule_id,
        "expected_decision": decision,
        "severity": severity,
        "injected_by": "synthetic_test",
        "description": "Synthetic evaluation fixture.",
    }


def _finding(
    *,
    rule_id: str = "VR-001",
    entity_type: str = "employee",
    entity_id: str = "EMP-000001",
    employee_id: str | None = "EMP-000001",
    period_id: str | None = "PP-2026-01",
    severity: str = "High",
) -> dict[str, str | None]:
    return {
        "rule_id": rule_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "employee_id": employee_id,
        "period_id": period_id,
        "severity": severity,
    }


def _write_labels(path: Path, labels: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=GROUND_TRUTH_COLUMNS)
        writer.writeheader()
        writer.writerows(labels)


def _create_evaluation_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE validation_run (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL
            );
            CREATE TABLE exception (
                exception_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                employee_id TEXT,
                period_id TEXT,
                severity TEXT NOT NULL
            );
            INSERT INTO validation_run VALUES
                ('RUN-000001', '2026-01-31T12:00:00'),
                ('RUN-000002', '2026-02-28T12:00:00');
            INSERT INTO exception VALUES
                ('EXC-000001', 'RUN-000002', 'VR-001', 'employee',
                 'EMP-000001', 'EMP-000001', NULL, 'High');
            """
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_perfect_detection_has_perfect_precision_recall_and_f1():
    result = evaluate_findings([_label()], [_finding()])

    assert result["overall"] == {
        "total_planted_issues": 1,
        "total_detected_issues": 1,
        "tp": 1,
        "fp": 0,
        "fn": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


def test_false_positive_is_counted():
    result = evaluate_findings(
        [_label()], [_finding(), _finding(entity_id="EMP-000002")]
    )

    assert result["overall"]["tp"] == 1
    assert result["overall"]["fp"] == 1
    assert result["overall"]["fn"] == 0
    assert result["overall"]["precision"] == 0.5
    assert result["unmatched_findings"][0]["entity_id"] == "EMP-000002"


def test_false_negative_is_counted():
    result = evaluate_findings([_label()], [])

    assert result["overall"]["tp"] == 0
    assert result["overall"]["fp"] == 0
    assert result["overall"]["fn"] == 1
    assert result["overall"]["recall"] == 0.0
    assert result["unmatched_ground_truth"][0]["gt_id"] == "GT-000001"


def test_mixed_detection_scores_multiple_rules_and_issues():
    labels = [
        _label(),
        _label(
            gt_id="GT-000002",
            issue_type="missing_tax",
            rule_id="VR-002",
            entity_id="EMP-000002",
            employee_id="EMP-000002",
        ),
    ]
    findings = [
        _finding(),
        _finding(rule_id="VR-009", entity_id="PIN-EMP-000003-2026-01",
                 entity_type="payroll_input", employee_id="EMP-000003"),
    ]

    result = evaluate_findings(labels, findings)

    assert result["overall"]["tp"] == 1
    assert result["overall"]["fp"] == 1
    assert result["overall"]["fn"] == 1
    assert result["by_rule_id"]["VR-002"]["fn"] == 1
    assert result["by_rule_id"]["VR-009"]["fp"] == 1
    assert result["by_issue_type"]["missing_tax"]["fn"] == 1
    assert result["by_issue_type"]["unmatched"]["fp"] == 1


def test_zero_denominators_return_zero_without_error():
    empty = evaluate_findings([], [])
    findings_only = evaluate_findings([], [_finding()])

    assert empty["overall"]["precision"] == 0
    assert empty["overall"]["recall"] == 0
    assert empty["overall"]["f1"] == 0
    assert findings_only["overall"]["precision"] == 0
    assert findings_only["overall"]["recall"] == 0
    assert findings_only["overall"]["f1"] == 0


def test_duplicate_findings_for_one_planted_issue_count_once_as_true_positive():
    result = evaluate_findings([_label()], [_finding(), _finding()])

    assert result["overall"]["tp"] == 1
    assert result["overall"]["fp"] == 1
    assert result["overall"]["fn"] == 0
    assert result["false_positive_findings"][0]["reason"] == "duplicate_detection"
    assert result["unmatched_findings"] == []
    assert result["unmatched_finding_classification"]["total"] == 0


@pytest.mark.parametrize(
    "wrong_finding",
    [
        _finding(rule_id="VR-002"),
        _finding(entity_type="time_entry"),
        _finding(entity_id="EMP-000002"),
        _finding(employee_id="EMP-000002"),
        _finding(period_id="PP-2026-02"),
    ],
)
def test_matching_requires_rule_entity_identity_and_matching_context(wrong_finding):
    result = evaluate_findings([_label()], [wrong_finding])

    assert result["overall"]["tp"] == 0
    assert result["overall"]["fp"] == 1
    assert result["overall"]["fn"] == 1


def test_missing_context_on_existing_rule_does_not_prevent_identity_match():
    result = evaluate_findings(
        [_label()], [_finding(period_id=None)]
    )

    assert result["overall"]["tp"] == 1


def test_unmatched_ground_truth_and_finding_are_reported():
    result = evaluate_findings(
        [_label()],
        [
            _finding(
                rule_id="VR-003",
                entity_type="time_entry",
                entity_id="TIME-EMP-000001-2026-01-02",
            )
        ],
    )

    assert result["unmatched_ground_truth"][0]["gt_id"] == "GT-000001"
    assert result["unmatched_findings"][0]["rule_id"] == "VR-003"
    assert result["overall"]["tp"] == 0
    assert result["overall"]["fp"] == 1
    assert result["overall"]["fn"] == 1
    assert result["unmatched_findings"][0]["classification"] == "secondary_detection"
    assert result["unmatched_finding_classification"] == {
        "total": 1,
        "by_category": {
            "secondary_detection": 1,
            "unlabelled_finding": 0,
            "known_negative_detection": 0,
        },
        "by_rule_id": {
            "VR-003": {
                "secondary_detection": 1,
                "unlabelled_finding": 0,
                "known_negative_detection": 0,
                "total": 1,
            }
        },
    }


def test_unlabelled_finding_has_separate_classification_by_rule():
    result = evaluate_findings(
        [],
        [
            _finding(
                rule_id="VR-011",
                entity_type="time_entry",
                entity_id="TIME-EMP-000001-2026-01-02",
            )
        ],
    )

    assert result["overall"]["tp"] == 0
    assert result["overall"]["fp"] == 1
    assert result["overall"]["fn"] == 0
    assert result["unmatched_findings"][0]["classification"] == "unlabelled_finding"
    assert result["unmatched_finding_classification"]["by_rule_id"]["VR-011"][
        "unlabelled_finding"
    ] == 1


def test_known_negative_boundary_is_a_false_positive_not_a_planted_issue():
    control = _label(
        decision="PASS",
        issue_type="boundary_exact_max_hours",
        rule_id="VR-004",
        entity_type="payroll_input",
        entity_id="PIN-EMP-000001-2026-01",
        severity="High",
    )
    result = evaluate_findings(
        [control],
        [
            _finding(
                rule_id="VR-004",
                entity_type="payroll_input",
                entity_id="PIN-EMP-000001-2026-01",
            )
        ],
    )

    assert result["overall"]["total_planted_issues"] == 0
    assert result["overall"]["tp"] == 0
    assert result["overall"]["fp"] == 1
    assert result["by_issue_type"]["boundary_exact_max_hours"]["negative_controls"] == 1
    assert result["false_positive_findings"][0]["reason"] == "known_negative_detected"
    assert result["unmatched_findings"][0]["classification"] == (
        "known_negative_detection"
    )
    assert result["unmatched_finding_classification"]["by_rule_id"]["VR-004"][
        "known_negative_detection"
    ] == 1


def test_missing_and_malformed_ground_truth_input_raise_clear_errors(tmp_path):
    missing_path = tmp_path / "missing.csv"
    database_path = tmp_path / "empty.db"
    _create_evaluation_database(database_path)
    with pytest.raises(EvaluationError, match="not found"):
        evaluate_dataset(database_path, missing_path)

    malformed_path = tmp_path / "malformed.csv"
    malformed_path.write_text("gt_id,issue_type\nGT-000001,missing_bank\n", encoding="utf-8")
    with pytest.raises(EvaluationError, match="columns"):
        evaluate_findings_from_file(malformed_path)

    malformed_row = tmp_path / "malformed-row.csv"
    malformed_row.write_text(
        ",".join(GROUND_TRUTH_COLUMNS) + "\nGT-000001,missing_bank\n",
        encoding="utf-8",
    )
    with pytest.raises(EvaluationError, match="invalid shape"):
        evaluate_findings_from_file(malformed_row)


def evaluate_findings_from_file(path: Path) -> dict:
    from backend.evaluation.scorecard import _read_labels

    return evaluate_findings(_read_labels(path), [])


def test_evaluation_does_not_modify_database_or_ground_truth(tmp_path):
    database_path = tmp_path / "dataset.db"
    labels_path = tmp_path / "labels.csv"
    manifest_path = tmp_path / "manifest.json"
    _create_evaluation_database(database_path)
    _write_labels(labels_path, [_label()])
    manifest_path.write_text(
        json.dumps(
            {
                "seed": 9,
                "parameters": {"size": "synthetic", "employee_count": 1},
            }
        ),
        encoding="utf-8",
    )
    before = {
        path: _sha256(path)
        for path in (database_path, labels_path, manifest_path)
    }

    result = evaluate_dataset(
        database_path, labels_path, manifest_path=manifest_path
    )

    assert result["validation_run_id"] == "RUN-000002"
    assert result["dataset"] == {
        "identifier": tmp_path.name,
        "size": "synthetic",
        "employee_count": 1,
        "seed": 9,
    }
    assert result["overall"]["tp"] == 1
    assert {path: _sha256(path) for path in before} == before


def test_missing_validation_run_is_reported_without_database_mutation(tmp_path):
    database_path = tmp_path / "empty.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE validation_run (run_id TEXT, started_at TEXT);
            CREATE TABLE exception (
                exception_id TEXT, run_id TEXT, rule_id TEXT, entity_type TEXT,
                entity_id TEXT, employee_id TEXT, period_id TEXT, severity TEXT
            );
            """
        )
    labels_path = tmp_path / "labels.csv"
    _write_labels(labels_path, [])
    original = _sha256(database_path)

    with pytest.raises(EvaluationError, match="No validation run"):
        evaluate_dataset(database_path, labels_path)

    assert _sha256(database_path) == original


def test_validation_engine_has_no_evaluation_or_ground_truth_dependency():
    from backend.services import validation_engine

    source = inspect.getsource(validation_engine)
    assert "backend.evaluation" not in source
    assert "ground_truth" not in source
    assert "labels.csv" not in source


def test_approval_export_has_no_ground_truth_dependency():
    from backend.services import approval_export

    source = inspect.getsource(approval_export)
    assert "ground_truth" not in source
    assert "labels.csv" not in source


def test_evaluation_endpoint_redacts_label_and_employee_identifiers(tmp_path):
    database_path = tmp_path / "dataset.db"
    labels_path = tmp_path / "labels.csv"
    manifest_path = tmp_path / "manifest.json"
    _create_evaluation_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO exception VALUES
                ('EXC-000002', 'RUN-000002', 'VR-003', 'time_entry',
                 'TIME-EMP-000001-2026-01-02', 'EMP-000001',
                 'PP-2026-01', 'Medium')
            """
        )
    _write_labels(labels_path, [_label()])
    manifest_path.write_text(
        json.dumps({"parameters": {"size": "synthetic", "employee_count": 1}}),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            database_path,
            ground_truth_path=labels_path,
            manifest_path=manifest_path,
        )
    )

    response = client.get("/evaluation/scorecard")

    assert response.status_code == 200
    assert response.json()["overall"]["tp"] == 1
    assert response.json()["overall"]["fp"] == 1
    assert response.json()["unmatched_finding_classification"]["by_category"][
        "secondary_detection"
    ] == 1
    assert response.json()["unmatched_findings"][0]["classification"] == (
        "secondary_detection"
    )
    body = response.text
    assert "GT-000001" not in body
    assert "EMP-000001" not in body


def test_starter_dataset_integration_uses_copy_and_persisted_validation_findings(
    tmp_path,
):
    from backend.db.connection import get_connection
    from backend.services.validation_engine import run_validation

    dataset_root = Path(__file__).parents[2] / "data" / "module3-starter"
    source_database = dataset_root / "paygate.db"
    copy_path = tmp_path / "paygate.db"
    shutil.copy2(source_database, copy_path)
    connection = get_connection(copy_path)
    try:
        validation_result = run_validation(connection)
        connection.commit()
        result = evaluate_dataset(
            copy_path,
            dataset_root / "ground_truth" / "labels.csv",
            manifest_path=dataset_root / "manifest.json",
            run_id=validation_result.run_id,
        )
    finally:
        connection.close()

    assert result["validation_run_id"] == validation_result.run_id
    assert result["dataset"]["size"] == "starter"
    assert result["overall"]["total_planted_issues"] > 0
    assert result["overall"]["total_detected_issues"] == (
        result["overall"]["tp"] + result["overall"]["fp"]
    )
    assert result["overall"] == {
        "total_planted_issues": 13,
        "total_detected_issues": 84,
        "tp": 13,
        "fp": 71,
        "fn": 0,
        "precision": 13 / 84,
        "recall": 1.0,
        "f1": 2 * (13 / 84) / (13 / 84 + 1.0),
    }
    assert result["unmatched_finding_classification"]["by_category"] == {
        "secondary_detection": 27,
        "unlabelled_finding": 44,
        "known_negative_detection": 0,
    }
    assert result["unmatched_finding_classification"]["by_rule_id"] == {
        "VR-004": {
            "secondary_detection": 1,
            "unlabelled_finding": 0,
            "known_negative_detection": 0,
            "total": 1,
        },
        "VR-005": {
            "secondary_detection": 26,
            "unlabelled_finding": 42,
            "known_negative_detection": 0,
            "total": 68,
        },
        "VR-011": {
            "secondary_detection": 0,
            "unlabelled_finding": 2,
            "known_negative_detection": 0,
            "total": 2,
        },
    }
