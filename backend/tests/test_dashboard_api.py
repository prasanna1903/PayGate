"""Tests for dashboard data and manual validation API endpoints."""

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.tests.validation_support import create_validation_database


def test_dashboard_summary_and_paginated_payroll_inputs(tmp_path):
    database_path = tmp_path / "dashboard.db"
    connection = create_validation_database(database_path)
    connection.close()
    client = TestClient(create_app(database_path))

    summary = client.get("/dashboard/summary")
    inputs = client.get("/payroll-inputs?limit=1&offset=0")

    assert summary.status_code == 200
    assert summary.json()["employee_count"] == 1
    assert summary.json()["payroll_input_count"] == 1
    assert summary.json()["validation_finding_count"] == 0
    assert summary.json()["blocked_input_count"] == 0
    assert summary.json()["successful_export_count"] == 1
    assert summary.json()["latest_validation_run"] is None
    assert summary.json()["export_options"][0]["period_id"] == "PP-2026-01"
    assert inputs.status_code == 200
    assert inputs.json()["total"] == 1
    assert inputs.json()["items"][0]["status"] == "APPROVED"


def test_manual_validation_returns_real_findings_and_dashboard_updates(tmp_path):
    database_path = tmp_path / "dashboard-validation.db"
    connection = create_validation_database(database_path)
    connection.execute(
        "UPDATE employee SET tax_id = NULL WHERE employee_id = 'EMP-000001'"
    )
    connection.commit()
    connection.close()
    client = TestClient(create_app(database_path))

    response = client.post("/validation/runs")
    assert response.status_code == 200
    run = response.json()
    assert run["run_id"] == "RUN-000001"
    assert run["finding_count"] == 1
    assert run["findings"][0]["rule_id"] == "VR-002"
    assert run["findings"][0]["message"]
    assert run["findings"][0]["evidence"]["tax_id_missing"] is True
    assert run["blocked_inputs"] == ["PIN-EMP-000001-2026-01"]

    summary = client.get("/dashboard/summary").json()
    assert summary["latest_validation_run"]["run_id"] == run["run_id"]
    assert summary["validation_finding_count"] == 1
    assert summary["blocked_input_count"] == 1

    exceptions = client.get("/exceptions?status=OPEN").json()
    assert exceptions["total"] == 1
    assert exceptions["items"][0]["exception_id"] == "EXC-000001"
    assert exceptions["items"][0]["message"] == run["findings"][0]["message"]


def test_dashboard_list_filters_and_cors_for_configured_frontend(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYGATE_CORS_ORIGINS", "http://localhost:5173")
    database_path = tmp_path / "dashboard-filters.db"
    connection = create_validation_database(database_path)
    connection.close()
    client = TestClient(create_app(database_path))

    response = client.get(
        "/payroll-inputs?status=APPROVED&query=EMP-000001",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_invalid_dashboard_pagination_returns_bad_request():
    client = TestClient(create_app())

    response = client.get("/exceptions?limit=0")

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid request."
