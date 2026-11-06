"""FastAPI application for PayGate workflow endpoints."""

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.api.models import ErrorResponse
from backend.api.routers.workflow import create_workflow_router
from backend.generator.config import load_config
from backend.services.approval_export import WorkflowError


def create_app(database_path: str | Path | None = None) -> FastAPI:
    """Build the API, optionally overriding the configured SQLite database."""
    path = load_config().database_path if database_path is None else database_path
    app = FastAPI(title="PayGate API")
    app.include_router(create_workflow_router(path))

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
