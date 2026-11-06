"""Pydantic request and response models for payroll workflow endpoints."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ApprovalRequest(BaseModel):
    approver_id: str = Field(min_length=1)
    comment: str = Field(min_length=1)
    approver_role: str = Field(default="HR", min_length=1)

    @field_validator("approver_id", "comment", "approver_role")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class WaiverRequest(BaseModel):
    approver_id: str = Field(min_length=1)
    comment: str = Field(min_length=1)

    @field_validator("approver_id", "comment")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ExportRequest(BaseModel):
    pay_group_id: str = Field(min_length=1)
    period_id: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)

    @field_validator("pay_group_id", "period_id", "requested_by")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ApprovalResponse(BaseModel):
    approval_id: str
    payroll_input_id: str
    status: Literal["APPROVED"]
    approver_id: str
    comment: str


class WaiverResponse(BaseModel):
    approval_id: str
    exception_id: str
    status: Literal["WAIVED"]
    approver_id: str
    comment: str


class ExportLineResponse(BaseModel):
    payroll_input_id: str
    employee_id: str
    period_id: str
    amount_minor: int


class ExportResponse(BaseModel):
    export_id: str
    pay_group_id: str
    period_id: str
    status: Literal["CREATED", "RELEASED"]
    line_count: int
    total_net_minor: int
    created_at: str
    lines: list[ExportLineResponse]


class ConflictReason(BaseModel):
    code: str
    message: str
    payroll_input_id: str | None = None
    exception_id: str | None = None
    time_entry_id: str | None = None
    export_id: str | None = None


class ErrorResponse(BaseModel):
    message: str
    reasons: list[ConflictReason] = Field(default_factory=list)
