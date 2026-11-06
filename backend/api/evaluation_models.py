"""Response models for the privacy-preserving evaluation endpoint."""

from typing import Any

from pydantic import BaseModel


class EvaluationCategoryMetrics(BaseModel):
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    planted_issues: int
    negative_controls: int


class EvaluationOverallMetrics(BaseModel):
    total_planted_issues: int
    total_detected_issues: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


class RedactedGroundTruthItem(BaseModel):
    issue_type: str
    rule_id: str
    severity: str


class RedactedFindingItem(BaseModel):
    rule_id: str
    entity_type: str
    severity: str
    classification: str


class UnmatchedFindingClassification(BaseModel):
    total: int
    by_category: dict[str, int]
    by_rule_id: dict[str, dict[str, int]]


class EvaluationResponse(BaseModel):
    dataset: dict[str, Any]
    validation_run_id: str
    overall: EvaluationOverallMetrics
    by_rule_id: dict[str, EvaluationCategoryMetrics]
    by_issue_type: dict[str, EvaluationCategoryMetrics]
    by_severity: dict[str, EvaluationCategoryMetrics]
    unmatched_finding_classification: UnmatchedFindingClassification
    unmatched_ground_truth: list[RedactedGroundTruthItem]
    unmatched_findings: list[RedactedFindingItem]
