# PayGate Workflow API

The workflow API uses the configured SQLite database (`DB_PATH`, or the
project's default database path). `backend.api.app:app` is the ASGI application;
`create_app(database_path)` can be used to bind an application to a specific
database, including an isolated test database.

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
