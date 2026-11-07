# PayGate — Payroll Validation Before Export

PayGate is a payroll operations prototype that validates payroll inputs before
they can be approved and exported. It records validation findings as
exceptions, supports human approval and exception waiver workflows, and
provides a scorecard that compares a validation run with configured
ground-truth labels.

## The problem

Payroll data is assembled from employee, attendance, leave, and pay-period
records. A missing or inconsistent source record can lead to incorrect pay or
an export that needs costly correction. Reviewing data only after export makes
mistakes harder to contain.

PayGate places validation and an approval gate before export. For example, if
a pay group's configured maximum is 80 hours for a period but attendance
records total 84 hours, the validation rules can flag the excess for review
before the payroll input is approved or exported. The example is illustrative;
the applicable threshold comes from the configured payroll data.

## Objectives

- Detect configured payroll-data inconsistencies before export.
- Persist validation runs and their findings for review.
- Require approval and enforce blocking-exception checks at the export gate.
- Preserve approval, waiver, and export workflow records.
- Measure validation results against a labeled evaluation dataset.

## Features and workflow

The implemented workflow is:

**Payroll data → Validation engine → Exceptions → Human review → Approval or
waiver → Export gate**

1. Payroll, employee, and related records are stored in the configured SQLite
   database.
2. A manual validation run executes the validation engine and persists the
   run and findings. Blocking findings can block associated payroll inputs.
3. A reviewer inspects payroll inputs and exceptions through the dashboard or
   API.
4. An eligible input can be approved. A blocking exception can be waived by
   an approver with a non-empty comment. Approval and waiver actor details are
   recorded, but are not authenticated by the application.
5. An export is rejected unless all inputs in the requested pay-group and
   period scope are approved, no unresolved blocking exceptions remain, and
   linked source time entries are approved. A successful export is recorded
   and transitions the included inputs to `EXPORTED`.

Other implemented features include:

- Dashboard summary counts, latest validation run, available pay-group and
  period combinations, and recent exports.
- Paginated and filterable payroll-input and exception lists.
- Evaluation of the latest persisted validation run against ground-truth
  labels, with identifier fields redacted in the HTTP scorecard response.

## Technology

- **Backend:** Python, FastAPI, Pydantic, Uvicorn, SQLite.
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, Recharts, and
  `lucide-react`.
- **Testing:** pytest and HTTPX.
- **Data utilities:** NumPy and pandas.

Python packages are listed in [`requirements.txt`](./requirements.txt).
Frontend runtime and development dependencies are listed in
[`frontend/package.json`](./frontend/package.json).

## Project structure

```text
PayGate/
├── backend/
│   ├── api/
│   │   └── app.py
│   └── tests/
├── frontend/
│   └── package.json
├── docs/
│   └── API.md
├── data/                 # Default SQLite database path in .env.example
├── .env.example
├── requirements.txt
└── README.md
```

The backend tests cover validation rules and runs, approval and export
workflows, evaluation, API behavior, configuration, identifiers, dataset
generation and checks, and database schema expectations.

## Prerequisites

- Python and pip.
- Node.js and npm.
- PowerShell on Windows.

The inspected dependency files do not declare minimum Python or Node.js
versions.

## Install on Windows

Run these commands from the repository root (`PayGate/`):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell prevents activation due to the current process execution policy,
you can activate the environment for this terminal session with:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Install frontend dependencies from the frontend directory:

```powershell
Set-Location .\frontend
npm install
```

## Configuration

The root [`.env.example`](./.env.example) lists these settings and example
values:

| Variable | Example | Purpose |
|---|---|---|
| `SEED` | `20261022` | Synthetic-data seed. |
| `DB_PATH` | `./data/paygate.db` | SQLite database path used by the API. |
| `GROUND_TRUTH_DIR` | `./ground_truth` | Ground-truth directory used for evaluation. |
| `PAYGATE_EMPLOYEE_COUNT` | `3000` | Employee-count setting. |
| `PAYGATE_PAY_PERIODS` | `PP-2026-01,PP-2026-02,PP-2026-03` | Comma-separated pay periods. |

The API also reads `PAYGATE_CORS_ORIGINS` for cross-origin frontend access; its
default allowed origins are `http://localhost:5173` and
`http://127.0.0.1:5173`.

The example file is a reference, not a PowerShell environment loader. Set
variables in the current PowerShell session before starting the backend, for
example from the repository root:

```powershell
$env:DB_PATH = ".\data\paygate.db"
$env:GROUND_TRUTH_DIR = ".\ground_truth"
$env:PAYGATE_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

PowerShell environment variables set this way apply to processes started from
that terminal. Point `DB_PATH` at a database containing the required PayGate
tables and data. For evaluation, configure a ground-truth directory containing
the labels for the dataset being evaluated.

## Run the applications

### FastAPI backend

From the repository root, with the virtual environment active and environment
variables configured as needed:

```powershell
python -m uvicorn backend.api.app:app --reload
```

### React frontend

Open a second PowerShell terminal. From the repository root:

```powershell
Set-Location .\frontend
npm run dev
```

The Vite development frontend uses a same-origin `/api` proxy to the local
backend.

### URLs

- **Dashboard:** [http://localhost:5173](http://localhost:5173)
- **FastAPI interactive documentation:**
  [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

The dashboard requires both the frontend and backend to be running. The
backend must also be pointed at an initialized database.

## API endpoint reference

The API is documented in [`docs/API.md`](./docs/API.md). Its documented routes
include:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/dashboard/summary` | Summary counts, latest run, export options, and recent exports. |
| `GET` | `/payroll-inputs` | Paginated payroll inputs; supports status and text filters. |
| `GET` | `/exceptions` | Paginated exception records; supports status and text filters. |
| `POST` | `/validation/runs` | Run and persist a manual validation run. |
| `POST` | `/payroll-inputs/{payroll_input_id}/approval` | Approve an eligible payroll input. |
| `POST` | `/exceptions/{exception_id}/waiver` | Record a waiver for an eligible blocking exception. |
| `POST` | `/exports` | Request an export for a pay-group and pay-period scope. |
| `GET` | `/exports/{export_id}` | Retrieve export details. |
| `GET` | `/evaluation/scorecard` | Retrieve the latest run's evaluation scorecard. |

## Evaluation

The scorecard compares findings from the latest persisted validation run with
the configured ground-truth CSV:

- **True positive (TP):** a finding that matches a planted `FLAG` label.
- **False positive (FP):** a finding that does not represent a unique planted
  issue, including extra detections, known-negative `PASS` matches, and
  unmatched findings.
- **False negative (FN):** a planted `FLAG` label with no matching finding.
- **Precision:** `TP / (TP + FP)`.
- **Recall:** `TP / (TP + FN)`.
- **F1:** `2 × precision × recall / (precision + recall)`.

Zero denominators produce zero-valued metrics. The scorecard also reports
breakdowns and unmatched-finding classifications. These classifications
describe findings and do not change TP, FP, or FN.

## Limitations

- The application has no authentication provider. Supplied actor identities
  for approval and waiver are recorded but are not independently verified.
- The evaluation dataset contains a finite set of planted cases and negative
  controls; it does not label every legitimate or erroneous payroll condition.
- An unmatched finding is counted as a false positive relative to the
  available labels. That evaluation convention does not establish that the
  finding is incorrect in real operations.
- The scorecard requires a persisted validation run and configured labels. It
  reports the latest run and does not run validation itself.
- The API does not synthesize a recommended next step for exceptions.

## AI-assisted development disclosure

AI assistance was used to prepare this README. The reviewed repository files
do not provide a complete, verifiable historical record of prompts submitted
to every AI tool during project development. The examples below are
representative themes based on implemented project functionality; they are
not verbatim quotations and are not a complete historical prompt log.

### Representative prompt themes

- “Add pre-export payroll validation that records findings for human review.”
- “Enforce approval and blocking-exception checks before creating an export.”
- “Build a dashboard for payroll inputs, exceptions, validation runs, and
  export status.”
- “Evaluate persisted validation findings against labeled cases using
  precision, recall, and F1.”

## Tests and production build

Run the backend tests from the repository root:

```powershell
python -m pytest -q
```

Build the frontend from its directory:

```powershell
Set-Location .\frontend
npm run build
```

Most recently verified in this workspace: **174 backend tests passed** (with
one Starlette deprecation warning from the FastAPI test client), and the
frontend TypeScript/Vite production build passed.
