"""Response models for dashboard and validation-run endpoints."""

from typing import Any

from pydantic import BaseModel


class ValidationRunSummary(BaseModel):
    run_id: str
    started_at: str
    finding_count: int
    blocked_input_count: int
    validated_input_count: int


class ExportOption(BaseModel):
    pay_group_id: str
    pay_group_name: str
    period_id: str


class RecentExport(BaseModel):
    export_id: str
    pay_group_id: str
    period_id: str
    status: str
    total_net_minor: int
    created_at: str


class DashboardSummary(BaseModel):
    employee_count: int
    payroll_input_count: int
    validation_finding_count: int
    blocked_input_count: int
    successful_export_count: int
    latest_validation_run: ValidationRunSummary | None
    export_options: list[ExportOption]
    recent_exports: list[RecentExport]


class PayrollInputItem(BaseModel):
    payroll_input_id: str
    employee_id: str
    employee_name: str
    pay_group_id: str
    period_id: str
    regular_hours: float
    ot_hours: float
    net_minor: int
    status: str


class ExceptionItem(BaseModel):
    exception_id: str
    run_id: str
    rule_id: str
    rule_name: str
    severity: str
    blocking: bool
    status: str
    entity_type: str
    entity_id: str
    employee_id: str | None
    period_id: str | None
    evidence: dict[str, Any]
    message: str | None


class PageResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[Any]


class ValidationFinding(BaseModel):
    exception_id: str
    rule_id: str
    rule_name: str
    severity: str
    blocking: bool
    status: str
    entity_type: str
    entity_id: str
    employee_id: str | None
    period_id: str | None
    evidence: dict[str, Any]
    message: str | None


class ValidationRunResponse(BaseModel):
    run_id: str
    started_at: str
    finding_count: int
    findings: list[ValidationFinding]
    blocked_inputs: list[str]
    validated_inputs: list[str]
