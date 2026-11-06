"""Read-only API route for the latest validation-run scorecard."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from backend.api.evaluation_models import EvaluationResponse
from backend.evaluation.scorecard import evaluate_dataset


def create_evaluation_router(
    database_path: str | Path,
    ground_truth_path: str | Path,
    manifest_path: str | Path | None = None,
) -> APIRouter:
    """Create the evaluation route for one configured dataset."""
    router = APIRouter()

    @router.get("/evaluation/scorecard", response_model=EvaluationResponse)
    def read_scorecard() -> dict[str, Any]:
        scorecard = evaluate_dataset(
            database_path,
            ground_truth_path,
            manifest_path=manifest_path,
        )
        # Local scorecards retain identity fields for audit and troubleshooting;
        # HTTP responses expose only aggregate categories, never label/entity IDs.
        scorecard["unmatched_ground_truth"] = [
            {
                "issue_type": item["issue_type"],
                "rule_id": item["rule_id"],
                "severity": item["severity"],
            }
            for item in scorecard["unmatched_ground_truth"]
        ]
        scorecard["unmatched_findings"] = [
            {
                "rule_id": item["rule_id"],
                "entity_type": item["entity_type"],
                "severity": item["severity"],
                "classification": item["classification"],
            }
            for item in scorecard["unmatched_findings"]
        ]
        scorecard.pop("false_positive_findings", None)
        return scorecard

    return router
