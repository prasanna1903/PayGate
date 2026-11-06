"""Ground-truth evaluation isolated from operational payroll workflows."""

from backend.evaluation.scorecard import (
    EvaluationError,
    evaluate_dataset,
    evaluate_findings,
)

__all__ = ["EvaluationError", "evaluate_dataset", "evaluate_findings"]
