# PayGate Workflow API

The workflow API uses the configured SQLite database (`DB_PATH`, or the
project's default database path). `backend.api.app:app` is the ASGI application;
`create_app(database_path)` can be used to bind an application to a specific
database, including an isolated test database.

## Dashboard and validation data

The dashboard uses these additional operational routes. List endpoints are
paginated (`limit` 1–200, default 50; `offset` default 0) and do not read
ground-truth files.

### `GET /dashboard/summary`

Returns employee, payroll-input, latest-run finding, blocked-input, and
released-export counts; latest run metadata; pay-group/period combinations
from `paygroup_period_calendar`; and up to five recent exports. `latest_validation_run`
is `null` until validation has run. The finding count is scoped to the latest
persisted run.

### `GET /payroll-inputs`

Returns paginated payroll inputs with employee ID/name, pay group, period,
hours, net amount in integer minor units, and status. Optional `status` is an
exact status filter; optional `query` searches input ID, employee ID/name, and
period ID.

### `GET /exceptions`

Returns paginated exception records with rule name/ID, severity, blocking flag,
status, entity and employee/period context, evidence JSON, and the original
validation event message when recorded. Optional `status` is an exact status
filter; `query` searches exception/rule/entity/employee/period IDs. The schema
does not store a recommended-next-step field, so the API does not synthesize
one.

### `POST /validation/runs`

Runs the existing validation engine with trigger `manual` and returns the
persisted run ID, timestamp, findings and evidence, plus blocked and validated
payroll-input IDs. This uses the same operational validation engine; it does
not read evaluation labels.

The Vite development frontend defaults to a same-origin `/api` proxy to the
local API. Direct cross-origin frontend deployments are permitted by default
from `http://localhost:5173` and `http://127.0.0.1:5173`; configure the
comma-separated `PAYGATE_CORS_ORIGINS` environment variable with the exact
trusted origins for deployment.

All amounts are integer minor units. Approval and waiver requests record the
provided actor identity in the audit tables. The current project has no
authentication provider, so these identity fields are recorded but are not
independently authenticated by the API.

## Approve a payroll input

`POST /payroll-inputs/{payroll_input_id}/approval`

An input in `VALIDATED` or `BLOCKED` state can be approved only when no
associated unresolved blocking exceptions (`OPEN` or `ACKNOWLEDGED`) remain.
This permits a previously blocked input to proceed after the relevant
exceptions are resolved or waived, without bypassing any other open blocker.
The operation atomically writes the `approval` row, changes the input to
`APPROVED`, and appends its `state_event`.

Request:

Abbreviated response example (category maps and unmatched summaries can contain
additional entries):

```json
{
  "approver_id": "HR-SYNTHETIC-01",
  "approver_role": "HR",
  "comment": "Reviewed and approved."
}
```

Response (`200`):

```json
{
  "approval_id": "APR-000001",
  "payroll_input_id": "PIN-EMP-000001-2026-01",
  "status": "APPROVED",
  "approver_id": "HR-SYNTHETIC-01",
  "comment": "Reviewed and approved."
}
```

Important errors: `400` for a missing/blank request field; `404` if the payroll
input does not exist; `409` if the current status is not `VALIDATED` or
`BLOCKED`, or an associated unresolved blocking exception remains. Conflict
responses include `message` and a `reasons` list.

## Waive a blocking exception

`POST /exceptions/{exception_id}/waiver`

The exception must be blocking and currently `OPEN` or `ACKNOWLEDGED`. A waiver
requires an HR approver identity and a non-empty comment. The operation records
an `approval` with decision `WAIVED`, updates the exception to `WAIVED` with a
reference to that approval, and appends a `state_event`. The exception itself
is retained as history; waiving one exception does not waive any other
exception.

Request:

```json
{
  "approver_id": "HR-SYNTHETIC-01",
  "comment": "Reviewed; waiver approved."
}
```

Response (`200`):

```json
{
  "approval_id": "APR-000002",
  "exception_id": "EXC-000001",
  "status": "WAIVED",
  "approver_id": "HR-SYNTHETIC-01",
  "comment": "Reviewed; waiver approved."
}
```

Important errors: `400` for a missing/blank approver or comment; `404` if the
exception does not exist; `409` if it is not blocking or is not in a waivable
state.

## Request a payroll export

`POST /exports`

An export is scoped to one pay group and pay period. Every payroll input in
that scope must be `APPROVED`; it must have no associated unresolved blocking
exception; and each linked source time entry must exist and be `APPROVED`.
Failed checks return `409` with a `reasons` array and create no export, export
lines, or input-state changes. A successful export creates lines using each
input's employee, period, and `net_minor`, writes `CREATED` and `RELEASED`
export events, transitions included inputs from `APPROVED` to `EXPORTED`, and
commits the records atomically. Only one export per pay-group/pay-period pair
is allowed.

Request:

```json
{
  "pay_group_id": "PG-001",
  "period_id": "PP-2026-01",
  "requested_by": "PAYROLL-SYNTHETIC-01"
}
```

Response (`201`):

```json
{
  "export_id": "PEX-2026-000001",
  "pay_group_id": "PG-001",
  "period_id": "PP-2026-01",
  "status": "RELEASED",
  "line_count": 1,
  "total_net_minor": 8000,
  "created_at": "2026-02-01T10:00:00+00:00",
  "lines": [
    {
      "payroll_input_id": "PIN-EMP-000001-2026-01",
      "employee_id": "EMP-000001",
      "period_id": "PP-2026-01",
      "amount_minor": 8000
    }
  ]
}
```

Important errors: `400` for a missing/blank request field; `404` for an
unknown pay group or period; `409` for no inputs, an existing export, a
non-approved input, an unresolved blocking exception, or a missing/unapproved
source time entry. Rejection reasons include the affected payroll input,
exception, or time-entry identifier where applicable.

## Retrieve export details

`GET /exports/{export_id}`

Response (`200`) has the same shape as the export response, including all
export lines and totals. An unknown export returns `404`.

## Retrieve the evaluation scorecard

`GET /evaluation/scorecard`

Returns metrics for the latest persisted validation run in the API's configured
database, compared with the configured dataset's ground-truth CSV. The endpoint
is read-only. It does not execute validation or modify operational records.
When no validation run exists, the endpoint returns `409`. A missing labels
file returns `404`; malformed labels or manifests return `400`.

The response contains the overall metrics and breakdowns by rule, issue type,
and severity, plus unmatched record summaries. It deliberately omits ground-
truth IDs and employee/entity identifiers. Local evaluator results include
those IDs for diagnosis; do not expose that unredacted service result directly
to external clients.

The endpoint's database and ground-truth paths are selected when creating the
application. The default application uses configured `DB_PATH` and
`GROUND_TRUTH_DIR`; an output-directory dataset can be bound using
`create_app(database_path=..., ground_truth_path=..., manifest_path=...)`.

The following is an abbreviated response example; unmatched finding arrays are
summaries and may contain more entries than shown.

```json
{
  "dataset": {
    "identifier": "module3-starter",
    "size": "starter",
    "employee_count": 200,
    "seed": 20261022
  },
  "validation_run_id": "RUN-000001",
  "overall": {
    "total_planted_issues": 13,
    "total_detected_issues": 84,
    "tp": 13,
    "fp": 71,
    "fn": 0,
    "precision": 0.15476190476190477,
    "recall": 1.0,
    "f1": 0.2680412371134021
  },
  "by_rule_id": {
    "VR-001": {
      "tp": 1,
      "fp": 0,
      "fn": 0,
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0,
      "planted_issues": 1,
      "negative_controls": 0
    }
  },
  "by_issue_type": {
    "missing_bank": {
      "tp": 1,
      "fp": 0,
      "fn": 0,
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0,
      "planted_issues": 1,
      "negative_controls": 0
    }
  },
  "by_severity": {
    "High": {
      "tp": 1,
      "fp": 0,
      "fn": 0,
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0,
      "planted_issues": 1,
      "negative_controls": 0
    }
  },
  "unmatched_finding_classification": {
    "total": 71,
    "by_category": {
      "secondary_detection": 27,
      "unlabelled_finding": 44,
      "known_negative_detection": 0
    },
    "by_rule_id": {
      "VR-004": {
        "secondary_detection": 1,
        "unlabelled_finding": 0,
        "known_negative_detection": 0,
        "total": 1
      },
      "VR-005": {
        "secondary_detection": 26,
        "unlabelled_finding": 42,
        "known_negative_detection": 0,
        "total": 68
      },
      "VR-011": {
        "secondary_detection": 0,
        "unlabelled_finding": 2,
        "known_negative_detection": 0,
        "total": 2
      }
    }
  },
  "unmatched_ground_truth": [],
  "unmatched_findings": [
    {
      "rule_id": "VR-005",
      "entity_type": "time_entry",
      "severity": "Medium",
      "classification": "secondary_detection"
    }
  ]
}
```

`total_detected_issues` is TP + FP. A finding matches at most one planted
label, and excess findings for that label count as false positives. Ground-
truth `PASS` rows are negative controls, not planted issues; a finding matching
one is a false positive. Unmatched-finding categories are additional
descriptions, not metric reclassifications: same-period findings for another
planted issue are `secondary_detection`, findings with no related planted issue
are `unlabelled_finding`, and exact `PASS` matches are
`known_negative_detection`. See [TESTING.md](./TESTING.md) for formulas and
matching details.
