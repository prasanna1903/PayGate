# PayGate — Payroll Validation Before Export

PayGate is a local payroll-validation prototype. It stores payroll data in
SQLite, runs configurable validation rules, records exceptions for human
review, and gates payroll export on approval and blocking-exception status. A
scorecard compares persisted findings with deterministic synthetic ground
truth.

## What PayGate does

Payroll data assembled from attendance, leave, employee, and pay-period
records can contain inconsistencies that lead to incorrect pay or failed
exports. PayGate checks configured data before export. For example, if the
attendance records for an employee exceed the configured maximum hours for a
pay period, a validation finding can be recorded and reviewed before the
related payroll input is approved. The threshold is read from the pay-group
data; the example does not introduce a new rule or threshold.

The workflow is:

**Payroll data → Validation engine → Exceptions → Human review → Approval or
waiver → Export gate**

- A manual validation run persists findings and can block payroll inputs.
- Reviewers can inspect payroll inputs and exceptions in the dashboard.
- Eligible inputs can be approved; eligible blocking exceptions can be waived
  with an approver identity and comment.
- Export is released only when the inputs in the requested pay-group/period
  scope are approved, there are no unresolved blocking exceptions, and linked
  source time entries are approved.
- The evaluation scorecard compares the latest persisted validation run with
  the configured ground-truth CSV.

Approval and waiver identities are recorded but are not authenticated by the
application.

## Technology

- Python 3.10 or newer (Python 3.12 recommended), FastAPI, Pydantic, Uvicorn,
  SQLite, NumPy, pandas, pytest, and HTTPX.
- React, TypeScript, Vite, Tailwind CSS, Recharts, and `lucide-react`.
- Node.js 18 or newer (Node.js 20 LTS recommended) and npm.

Backend dependencies are in [`requirements.txt`](./requirements.txt). Frontend
dependencies and scripts are in [`frontend/package.json`](./frontend/package.json)
and the committed npm lockfile.

## Repository layout

```text
PayGate/
├── backend/
│   ├── api/              # FastAPI app, models, and routers
│   ├── db/               # SQLite connection helper and schema
│   ├── evaluation/       # Ground-truth scorecard
│   ├── generator/        # Deterministic synthetic data generation
│   ├── rules/            # Payroll validation rules
│   ├── services/         # Validation and approval/export workflows
│   ├── tests/            # Backend tests
│   └── validation/       # Generated-dataset checks
├── data/
│   └── seed/             # Versioned CSV catalogs used by the generator
├── docs/                 # API, testing, data, and validation documentation
├── frontend/             # React/TypeScript/Vite application
├── scripts/              # Windows setup and startup scripts
├── .env.example
└── requirements.txt
```

Generated databases and datasets, the Python virtual environment, frontend
dependencies, and local `.env` configuration are not source dependencies and
are ignored by Git.

## Fresh setup on Windows

### Prerequisites

Install:

- Git for Windows.
- Python 3.12 (the setup script also accepts Python 3.10 or newer) with the
  Windows Python launcher enabled.
- Node.js 20 LTS (Node.js 18 or newer) with npm.
- Windows PowerShell.

### Clone the repository

Run in PowerShell:

```powershell
Set-Location $HOME
git clone https://github.com/prasanna1903/PayGate.git
Set-Location .\PayGate
```

### Install dependencies and generate the starter dataset

From the repository root:

```powershell
.\scripts\setup.ps1
```

Setup creates `.env` from [`.env.example`](./.env.example) if needed, creates
`.venv`, installs backend requirements, installs frontend packages from the
lockfile, and uses the existing generator and schema to create and validate a
200-employee starter dataset. The default generated files are:

```text
data/paygate-starter/paygate.db
data/paygate-starter/manifest.json
data/paygate-starter/ground_truth/labels.csv
```

Generation uses seed `20261022` and the existing project logic. Setup stages
new output and moves it into place only after validation. If a complete
dataset already exists, it validates and reuses it; if the target is present
but incomplete, setup stops rather than overwriting it. Choose a different
`DB_PATH`/ground-truth directory or inspect the existing files before retrying.
Automatic setup expects the database filename to be `paygate.db` and the
ground-truth directory to be its sibling `ground_truth`.

The generator creates the SQLite database schema as part of dataset
generation; there is no separate database initialization command.

## Configure the application

The backend startup script reads the supported settings in the root `.env`
file. Relative paths are resolved from the repository root. Setup creates the
file from `.env.example` without replacing an existing `.env`.

| Setting | Default | Use |
|---|---|---|
| `SEED` | `20261022` | Synthetic data seed. |
| `DB_PATH` | `./data/paygate-starter/paygate.db` | SQLite database. |
| `GROUND_TRUTH_DIR` | `./data/paygate-starter/ground_truth` | Evaluation labels directory. |
| `PAYGATE_EMPLOYEE_COUNT` | `200` | Dataset-size setting used by API configuration. |
| `PAYGATE_PAY_PERIODS` | `PP-2026-01,PP-2026-02,PP-2026-03` | Three consecutive monthly periods for generation. |
| `PAYGATE_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed development frontend origins. |

The frontend defaults to `/api`, which the Vite development server proxies to
the local FastAPI server at `http://127.0.0.1:8000`. The optional frontend
setting is documented in [`frontend/.env.example`](./frontend/.env.example).

## Start the application

### Backend terminal

From the repository root:

```powershell
.\scripts\start-backend.ps1
```

The script loads `.env`, checks for the generated database and labels, then
starts FastAPI on `127.0.0.1:8000`.

### Frontend terminal

Open a second PowerShell terminal, change to the repository root, and run:

```powershell
Set-Location .\PayGate
.\scripts\start-frontend.ps1
```

The dashboard is at [http://127.0.0.1:5173](http://127.0.0.1:5173). Interactive
API documentation is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs);
the OpenAPI schema is at [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json).
Press **Ctrl+C** in each terminal to stop its server.
If port 5173 is occupied, start the frontend with
`.\scripts\start-frontend.ps1 -Port 5174` and use
`http://127.0.0.1:5174`.

The scorecard requires a persisted validation run. After startup, trigger a
manual run using the dashboard's validation action or `POST /validation/runs`,
then open the evaluation scorecard. Operational validation does not read the
ground-truth CSV.

## API routes

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/dashboard/summary` | Dashboard counts, latest run, export options, recent exports. |
| `GET` | `/payroll-inputs` | Paginated inputs with optional status and query filters. |
| `GET` | `/exceptions` | Paginated exceptions with optional status and query filters. |
| `POST` | `/validation/runs` | Execute and persist a manual validation run. |
| `POST` | `/payroll-inputs/{payroll_input_id}/approval` | Approve an eligible payroll input. |
| `POST` | `/exceptions/{exception_id}/waiver` | Waive an eligible blocking exception. |
| `POST` | `/exports` | Request a pay-group/period export subject to the export gate. |
| `GET` | `/exports/{export_id}` | Retrieve export details. |
| `GET` | `/evaluation/scorecard` | Evaluate the latest persisted run against configured labels. |

See [`docs/API.md`](./docs/API.md) for request/response details and workflow
constraints.

## Run tests and build

From the repository root, run backend tests:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

Build the frontend:

```powershell
Set-Location .\frontend
npm run build
```

The dataset verification tool can also check an existing generated starter
dataset from the repository root without writing a report:

```powershell
& .\.venv\Scripts\python.exe .\scripts\validate_data.py .\data\paygate-starter --no-report
```

## Evaluation

- **TP:** a finding that matches one planted `FLAG` label.
- **FP:** an extra finding for an already-matched issue, a finding matching a
  `PASS` negative control, or an unmatched finding.
- **FN:** a `FLAG` label without a matching finding.
- **Precision:** `TP / (TP + FP)`.
- **Recall:** `TP / (TP + FN)`.
- **F1:** `2 × precision × recall / (precision + recall)`.

Zero denominators produce zero. Evaluation uses only the available finite set
of planted cases and negative controls; it does not label every legitimate
condition. An unmatched finding counts as an FP relative to this dataset, not
as a human determination that it is incorrect. The HTTP scorecard omits
ground-truth and employee/entity identifiers.

## Troubleshooting

- **PowerShell says scripts are disabled:** allow scripts for the current
  terminal only, then rerun setup:

  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .\scripts\setup.ps1
  ```

- **Python or Node.js is not found / too old:** install Python 3.12 and Node.js
  20 LTS, open a new PowerShell terminal, and rerun setup.
- **Setup reports an incomplete dataset:** it does not replace existing
  files. Inspect the configured database directory and either restore a
  complete generated dataset or choose a new local data path.
- **Dashboard cannot connect to the API:** keep both server terminals
  running; confirm the backend is at `127.0.0.1:8000` and the frontend uses
  the `/api` Vite proxy.
- **The scorecard reports no validation run:** run validation from the
  dashboard or call `POST /validation/runs` before requesting the scorecard.
- **Evaluation labels are missing:** confirm `GROUND_TRUTH_DIR` in `.env`
  contains `labels.csv`; the setup-generated default is
  `data/paygate-starter/ground_truth/labels.csv`.
- **Port 8000 is occupied:** stop the process using that port before starting
  the backend.
- **Port 5173 is occupied:** start the frontend with
  `.\scripts\start-frontend.ps1 -Port 5174`; the script keeps strict-port
  behavior so it never reports the wrong URL.

## Limitations

- This is a local prototype using SQLite; no authentication provider is
  configured. Approval and waiver actor IDs are recorded but not verified.
- The scorecard compares only the latest persisted validation run and needs
  configured ground-truth labels.
- Evaluation results depend on a finite synthetic dataset and are not a
  substitute for human adjudication or production payroll controls.
- The API does not synthesize recommended next steps for exceptions.

## AI-assisted development

AI assistance supported implementation guidance, debugging, documentation,
and testing. The developer reviewed the implementation and verified it with
backend tests and a frontend production build. See
[`AI_PROMPT_HISTORY.md`](./AI_PROMPT_HISTORY.md) for representative prompt
themes. They are summaries, not a verbatim or exhaustive historical record.
