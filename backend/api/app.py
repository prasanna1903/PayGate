"""FastAPI application for PayGate workflow endpoints."""

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.api.models import ErrorResponse
from backend.api.routers.evaluation import create_evaluation_router
from backend.api.routers.workflow import create_workflow_router
from backend.generator.config import load_config
from backend.evaluation.scorecard import EvaluationError
from backend.services.approval_export import WorkflowError


def create_app(
    database_path: str | Path | None = None,
    *,
    ground_truth_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> FastAPI:
    """Build the API, optionally binding database and evaluation dataset paths."""
    config = load_config()
    path = config.database_path if database_path is None else Path(database_path)
    manifest_candidates = (
        Path(manifest_path),
    ) if manifest_path is not None else (
        path.with_suffix(".manifest.json"),
        path.parent / "manifest.json",
    )
    selected_manifest = next(
        (candidate for candidate in manifest_candidates if candidate.is_file()),
        manifest_candidates[0],
    )
    if ground_truth_path is not None:
        selected_ground_truth = Path(ground_truth_path)
    else:
        dataset_size = "starter" if config.employee_count <= 200 else "full"
        ground_truth_candidates = (
            path.parent / "ground_truth" / "labels.csv",
            path.parent / "ground_truth" / f"{path.stem}_labels.csv",
            config.ground_truth_dir / f"{dataset_size}_labels.csv",
        )
        selected_ground_truth = next(
            (
                candidate
                for candidate in ground_truth_candidates
                if candidate.is_file()
            ),
            ground_truth_candidates[0],
        )
    app = FastAPI(title="PayGate API")
    app.include_router(create_workflow_router(path))
    app.include_router(
        create_evaluation_router(
            path, selected_ground_truth, selected_manifest
        )
    )

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(
        _request: Request, error: WorkflowError
    ) -> JSONResponse:
        payload = ErrorResponse(
            message=error.message, reasons=error.reasons
        ).model_dump(exclude_none=True)
        return JSONResponse(
            status_code=error.status_code,
            content=jsonable_encoder(payload),
        )

    @app.exception_handler(EvaluationError)
    async def evaluation_error_handler(
        _request: Request, error: EvaluationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"message": error.message},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=jsonable_encoder(
                {
                    "message": "Invalid request.",
                    "errors": error.errors(),
                }
            ),
        )

    @app.exception_handler(sqlite3.IntegrityError)
    async def database_integrity_error_handler(
        _request: Request, _error: sqlite3.IntegrityError
    ) -> JSONResponse:
        payload = ErrorResponse(
            message="The operation conflicts with current database constraints."
        )
        return JSONResponse(
            status_code=409,
            content=jsonable_encoder(payload.model_dump()),
        )

    return app


app = create_app()
