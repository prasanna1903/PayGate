"""Compare persisted validation findings with external ground-truth labels."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import csv
import json
from pathlib import Path
import sqlite3
from typing import Any


GROUND_TRUTH_COLUMNS = (
    "gt_id",
    "issue_type",
    "entity_type",
    "entity_id",
    "employee_id",
    "period_id",
    "expected_rule_id",
    "expected_decision",
    "severity",
    "injected_by",
    "description",
)

UNMATCHED_FINDING_CATEGORIES = (
    "secondary_detection",
    "unlabelled_finding",
    "known_negative_detection",
)


class EvaluationError(Exception):
    """Ground-truth, database, or validation-run problem during evaluation."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _read_labels(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != GROUND_TRUTH_COLUMNS:
                raise EvaluationError(
                    "Ground-truth CSV columns do not match the supported format."
                )
            labels: list[dict[str, str]] = []
            seen_ids: set[str] = set()
            for row_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise EvaluationError(
                        f"Ground-truth CSV row {row_number} has an invalid shape."
                    )
                label = {key: value for key, value in row.items()}
                required = (
                    "gt_id",
                    "issue_type",
                    "entity_type",
                    "entity_id",
                    "expected_rule_id",
                    "expected_decision",
                    "severity",
                )
                if any(not label[key].strip() for key in required):
                    raise EvaluationError(
                        f"Ground-truth CSV row {row_number} is missing required values."
                    )
                if label["expected_decision"] not in ("FLAG", "PASS"):
                    raise EvaluationError(
                        f"Ground-truth CSV row {row_number} has an invalid decision."
                    )
                if label["gt_id"] in seen_ids:
                    raise EvaluationError(
                        f"Ground-truth CSV row {row_number} repeats a gt_id."
                    )
                seen_ids.add(label["gt_id"])
                labels.append(label)
            return labels
    except EvaluationError:
        raise
    except FileNotFoundError as error:
        raise EvaluationError("Ground-truth CSV was not found.", 404) from error
    except (OSError, UnicodeError, csv.Error) as error:
        raise EvaluationError("Ground-truth CSV could not be read.") from error


def _normalize_finding(finding: Any) -> dict[str, str | None]:
    if isinstance(finding, Mapping):
        get_value = finding.get
    else:
        get_value = lambda name, default=None: getattr(finding, name, default)

    result: dict[str, str | None] = {}
    for key in (
        "rule_id",
        "entity_type",
        "entity_id",
        "employee_id",
        "period_id",
        "severity",
    ):
        value = get_value(key)
        result[key] = None if value is None else str(value)
    if any(
        not result[key]
        for key in ("rule_id", "entity_type", "entity_id", "severity")
    ):
        raise EvaluationError("A validation finding is missing its identity fields.")
    return result


def _matches(
    label: Mapping[str, str],
    finding: Mapping[str, str | None],
) -> bool:
    # Rule, entity type, and entity ID define the issue identity. Employee and
    # period further constrain a match only when both sides provide the value,
    # since some existing rules (such as missing-bank) have no period context.
    for key in ("expected_rule_id", "entity_type", "entity_id"):
        finding_key = "rule_id" if key == "expected_rule_id" else key
        if label[key] != finding[finding_key]:
            return False
    for key in ("employee_id", "period_id"):
        expected = label.get(key) or None
        actual = finding.get(key) or None
        if expected is not None and actual is not None and expected != actual:
            return False
    return True


def _metrics(tp: int, fp: int, fn: int) -> dict[str, int | float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _category_breakdown(
    labels: list[dict[str, str]],
    findings: list[dict[str, str | None]],
    tp_label_indexes: set[int],
    false_positives: list[dict[str, Any]],
    category_key: str,
) -> dict[str, dict[str, int | float]]:
    category_expected_key = (
        "expected_rule_id" if category_key == "rule_id" else category_key
    )
    categories = {label[category_expected_key] for label in labels}
    categories.update(
        str(finding[category_key])
        for finding in findings
        if finding.get(category_key) is not None
    )
    result = {}
    for category in sorted(categories):
        expected_indexes = {
            index
            for index, label in enumerate(labels)
            if label["expected_decision"] == "FLAG"
            and label[category_expected_key] == category
        }
        category_tp = len(expected_indexes & tp_label_indexes)
        category_fn = len(expected_indexes - tp_label_indexes)
        category_fp = sum(
            1
            for false_positive in false_positives
            if false_positive["category_values"].get(category_key) == category
        )
        negative_controls = sum(
            1
            for label in labels
            if label["expected_decision"] == "PASS"
            and label[category_expected_key] == category
        )
        result[category] = {
            **_metrics(category_tp, category_fp, category_fn),
            "planted_issues": len(expected_indexes),
            "negative_controls": negative_controls,
        }
    return result


def evaluate_findings(
    labels: Sequence[Mapping[str, str]],
    findings: Iterable[Any],
    *,
    dataset: Mapping[str, Any] | None = None,
    validation_run_id: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic scorecard for supplied labels and findings.

    Each finding can satisfy at most one FLAG label. Extra findings matching an
    already detected label are false positives, not additional true positives.
    PASS labels are known-negative controls: a matching finding is a false
    positive, but the control is not counted as a planted issue or a false
    negative.
    """
    normalized_labels = [dict(label) for label in labels]
    required = (
        "gt_id",
        "issue_type",
        "entity_type",
        "entity_id",
        "expected_rule_id",
        "expected_decision",
        "severity",
    )
    seen_ids: set[str] = set()
    for label in normalized_labels:
        if any(
            not isinstance(label.get(key), str) or not label[key].strip()
            for key in required
        ):
            raise EvaluationError("A ground-truth record is missing required values.")
        if label["expected_decision"] not in ("FLAG", "PASS"):
            raise EvaluationError("Ground-truth decision must be FLAG or PASS.")
        if label["gt_id"] in seen_ids:
            raise EvaluationError("Ground-truth gt_id values must be unique.")
        seen_ids.add(label["gt_id"])

    normalized_findings = [_normalize_finding(finding) for finding in findings]
    normalized_findings.sort(
        key=lambda finding: tuple(
            finding[key] or ""
            for key in (
                "rule_id",
                "entity_type",
                "entity_id",
                "employee_id",
                "period_id",
            )
        )
    )
    positive_indexes = [
        index
        for index, label in enumerate(normalized_labels)
        if label["expected_decision"] == "FLAG"
    ]
    negative_indexes = [
        index
        for index, label in enumerate(normalized_labels)
        if label["expected_decision"] == "PASS"
    ]
    matched_positive: set[int] = set()
    false_positives: list[dict[str, Any]] = []
    unmatched_findings: list[dict[str, Any]] = []

    for finding in normalized_findings:
        positive_matches = [
            index
            for index in positive_indexes
            if _matches(normalized_labels[index], finding)
        ]
        available = [
            index for index in positive_matches if index not in matched_positive
        ]
        if available:
            matched_positive.add(available[0])
            continue

        if positive_matches:
            label = normalized_labels[positive_matches[0]]
            reason = "duplicate_detection"
        else:
            negative_matches = [
                index
                for index in negative_indexes
                if _matches(normalized_labels[index], finding)
            ]
            if negative_matches:
                label = normalized_labels[negative_matches[0]]
                reason = "known_negative_detected"
                classification = "known_negative_detection"
            else:
                label = None
                reason = "unmatched_finding"
                has_related_flag = any(
                    normalized_labels[index].get("employee_id")
                    and normalized_labels[index].get("period_id")
                    and finding.get("employee_id")
                    == normalized_labels[index]["employee_id"]
                    and finding.get("period_id")
                    == normalized_labels[index]["period_id"]
                    for index in positive_indexes
                )
                classification = (
                    "secondary_detection"
                    if has_related_flag
                    else "unlabelled_finding"
                )

        if not positive_matches:
            unmatched_findings.append(
                {**finding, "classification": classification}
            )

        false_positives.append(
            {
                "reason": reason,
                "finding": dict(finding),
                "matched_ground_truth": (
                    {
                        "gt_id": label["gt_id"],
                        "issue_type": label["issue_type"],
                        "rule_id": label["expected_rule_id"],
                        "severity": label["severity"],
                    }
                    if label is not None
                    else None
                ),
                "category_values": {
                    "rule_id": finding["rule_id"],
                    "issue_type": (
                        label["issue_type"] if label is not None else "unmatched"
                    ),
                    "severity": (
                        label["severity"] if label is not None else finding["severity"]
                    ),
                },
            }
        )

    total_tp = len(matched_positive)
    total_fp = len(false_positives)
    total_fn = len(positive_indexes) - total_tp
    unmatched_ground_truth = [
        {
            "gt_id": label["gt_id"],
            "issue_type": label["issue_type"],
            "entity_type": label["entity_type"],
            "entity_id": label["entity_id"],
            "employee_id": label.get("employee_id") or None,
            "period_id": label.get("period_id") or None,
            "rule_id": label["expected_rule_id"],
            "severity": label["severity"],
        }
        for index, label in enumerate(normalized_labels)
        if label["expected_decision"] == "FLAG" and index not in matched_positive
    ]
    breakdowns = {
        "rule_id": _category_breakdown(
            normalized_labels,
            normalized_findings,
            matched_positive,
            false_positives,
            "rule_id",
        ),
        "issue_type": _category_breakdown(
            normalized_labels,
            normalized_findings,
            matched_positive,
            false_positives,
            "issue_type",
        ),
        "severity": _category_breakdown(
            normalized_labels,
            normalized_findings,
            matched_positive,
            false_positives,
            "severity",
        ),
    }
    # For unmatched false positives there is no ground-truth issue type.
    if any(
        item["category_values"]["issue_type"] == "unmatched"
        for item in false_positives
    ):
        breakdowns["issue_type"]["unmatched"] = _metrics(
            0,
            sum(
                item["category_values"]["issue_type"] == "unmatched"
                for item in false_positives
            ),
            0,
        ) | {"planted_issues": 0, "negative_controls": 0}
    unmatched_by_category = {
        category: 0 for category in UNMATCHED_FINDING_CATEGORIES
    }
    unmatched_by_rule_id: dict[str, dict[str, int]] = {}
    for finding in unmatched_findings:
        category = finding["classification"]
        rule_id = str(finding["rule_id"])
        unmatched_by_category[category] += 1
        rule_counts = unmatched_by_rule_id.setdefault(
            rule_id,
            {
                **{name: 0 for name in UNMATCHED_FINDING_CATEGORIES},
                "total": 0,
            },
        )
        rule_counts[category] += 1
        rule_counts["total"] += 1
    detected_issue_count = total_tp + total_fp
    return {
        "dataset": dict(dataset or {}),
        "validation_run_id": validation_run_id,
        "overall": {
            "total_planted_issues": len(positive_indexes),
            "total_detected_issues": detected_issue_count,
            **_metrics(total_tp, total_fp, total_fn),
        },
        "by_rule_id": breakdowns["rule_id"],
        "by_issue_type": breakdowns["issue_type"],
        "by_severity": breakdowns["severity"],
        "unmatched_finding_classification": {
            "total": len(unmatched_findings),
            "by_category": unmatched_by_category,
            "by_rule_id": unmatched_by_rule_id,
        },
        "unmatched_ground_truth": unmatched_ground_truth,
        "unmatched_findings": unmatched_findings,
        "false_positive_findings": [
            {
                "reason": item["reason"],
                "finding": item["finding"],
                "matched_ground_truth": item["matched_ground_truth"],
            }
            for item in false_positives
        ],
    }


def _manifest_metadata(path: Path | None, database_path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {"identifier": database_path.stem}
    if path is None or not path.exists():
        return metadata
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError("Dataset manifest could not be read.") from error
    if not isinstance(manifest, dict):
        raise EvaluationError("Dataset manifest must contain a JSON object.")
    parameters = manifest.get("parameters", {})
    if not isinstance(parameters, dict):
        raise EvaluationError("Dataset manifest parameters must be an object.")
    metadata.update(
        {
            "identifier": path.parent.name or database_path.stem,
            "size": parameters.get("size"),
            "employee_count": parameters.get("employee_count"),
            "seed": manifest.get("seed"),
        }
    )
    return metadata


def _latest_run_findings(
    connection: sqlite3.Connection, run_id: str | None
) -> tuple[str, list[dict[str, str | None]]]:
    try:
        if run_id is None:
            run = connection.execute(
                """
                SELECT run_id FROM validation_run
                ORDER BY started_at DESC, run_id DESC LIMIT 1
                """
            ).fetchone()
            if run is None:
                raise EvaluationError("No validation run is available to evaluate.", 409)
            run_id = str(run[0])
        else:
            run = connection.execute(
                "SELECT run_id FROM validation_run WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise EvaluationError(f"Validation run {run_id} was not found.", 404)
        rows = connection.execute(
            """
            SELECT rule_id, entity_type, entity_id, employee_id, period_id, severity
            FROM exception
            WHERE run_id = ?
            ORDER BY rule_id, entity_type, entity_id, exception_id
            """,
            (run_id,),
        ).fetchall()
    except sqlite3.Error as error:
        raise EvaluationError("Database does not contain a readable validation run.") from error
    return run_id, [
        {
            "rule_id": row[0],
            "entity_type": row[1],
            "entity_id": row[2],
            "employee_id": row[3],
            "period_id": row[4],
            "severity": row[5],
        }
        for row in rows
    ]


def evaluate_dataset(
    database_path: str | Path,
    ground_truth_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate the latest persisted run using a read-only database connection."""
    database = Path(database_path)
    labels_file = Path(ground_truth_path)
    manifest_file = Path(manifest_path) if manifest_path is not None else None
    if not database.is_file():
        raise EvaluationError("Dataset database was not found.", 404)
    labels = _read_labels(labels_file)
    metadata = _manifest_metadata(manifest_file, database)
    uri = database.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        raise EvaluationError("Dataset database could not be opened.") from error
    try:
        connection.execute("PRAGMA query_only = ON")
        selected_run_id, findings = _latest_run_findings(connection, run_id)
        return evaluate_findings(
            labels,
            findings,
            dataset=metadata,
            validation_run_id=selected_run_id,
        )
    finally:
        connection.close()


__all__ = [
    "EvaluationError",
    "evaluate_dataset",
    "evaluate_findings",
]
