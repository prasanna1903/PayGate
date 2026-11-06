"""FastAPI routes for payroll approval, waiver, and export workflows."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends

from backend.api.models import (
    ApprovalRequest,
    ApprovalResponse,
    ExportRequest,
    ExportResponse,
    WaiverRequest,
    WaiverResponse,
)
from backend.db.connection import get_connection
from backend.services.approval_export import (
    approve_payroll_input,
    create_payroll_export,
    get_payroll_export,
    waive_exception,
)


def create_workflow_router(database_path: str | Path) -> APIRouter:
    """Create workflow routes bound to the selected SQLite database."""
    router = APIRouter()

    def database_connection() -> Iterator[sqlite3.Connection]:
        connection = get_connection(database_path)
        try:
            yield connection
        finally:
            connection.close()

    @router.post(
        "/payroll-inputs/{payroll_input_id}/approval",
        response_model=ApprovalResponse,
    )
    def approve_input(
        payroll_input_id: str,
        request: ApprovalRequest,
        connection: sqlite3.Connection = Depends(database_connection),
    ) -> dict[str, str]:
        return approve_payroll_input(
            connection,
            payroll_input_id,
            approver_id=request.approver_id,
            approver_role=request.approver_role,
            comment=request.comment,
        )

    @router.post(
        "/exceptions/{exception_id}/waiver",
        response_model=WaiverResponse,
    )
    def waive_blocking_exception(
        exception_id: str,
        request: WaiverRequest,
        connection: sqlite3.Connection = Depends(database_connection),
    ) -> dict[str, str]:
        return waive_exception(
            connection,
            exception_id,
            approver_id=request.approver_id,
            comment=request.comment,
        )

    @router.post("/exports", response_model=ExportResponse, status_code=201)
    def request_export(
        request: ExportRequest,
        connection: sqlite3.Connection = Depends(database_connection),
    ) -> dict[str, object]:
        return create_payroll_export(
            connection,
            request.pay_group_id,
            request.period_id,
            requested_by=request.requested_by,
        )

    @router.get("/exports/{export_id}", response_model=ExportResponse)
    def read_export(
        export_id: str,
        connection: sqlite3.Connection = Depends(database_connection),
    ) -> dict[str, object]:
        return get_payroll_export(connection, export_id)

    return router
