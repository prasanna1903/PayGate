# PayGate dashboard

The React, TypeScript, Vite, Tailwind CSS 3, and Recharts dashboard reads live
data from the existing FastAPI application. It does not read ground-truth files
or calculate payroll/evaluation metrics in the browser.

## Local setup (PowerShell)

From the repository root, create a local synthetic starter dataset if you do
not already have one. This writes only under `data/module8-local`:

```powershell
& .\.venv\Scripts\python.exe .\scripts\generate_data.py --size starter --out .\data\module8-local
```

Then start the API against it:

```powershell
$env:DB_PATH = (Resolve-Path .\data\module8-local\paygate.db).Path
$env:GROUND_TRUTH_DIR = (Resolve-Path .\data\module8-local\ground_truth).Path
$env:PAYGATE_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
& .\.venv\Scripts\python.exe -m uvicorn backend.api.app:app --reload
```

In another terminal:

```powershell
Set-Location .\frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

The development default `VITE_API_BASE_URL=/api` uses Vite's same-origin
proxy to `http://127.0.0.1:8000`. Set it to the reachable API origin for a
deployed frontend. Vite reads this value at startup; restart the development
server after changing it. For direct cross-origin deployment, the API's
`PAYGATE_CORS_ORIGINS` must include the frontend origin. Configure explicit
trusted origins rather than using a wildcard.

Build the static frontend bundle with:

```powershell
npm run build
```

## Connected API

- `GET /dashboard/summary`: counts, latest validation run, export options, and
  recent exports.
- `GET /payroll-inputs`: paginated input list with optional `status` and
  `query` filters.
- `GET /exceptions`: paginated findings, persisted evidence, and available
  lifecycle status; optional `status` and `query` filters.
- `POST /validation/runs`: execute and persist a manual validation run.
- `GET /evaluation/scorecard`: read the backend scorecard. The dashboard
  presents the configured dataset's available labels as the evaluation basis.
- `POST /payroll-inputs/{payroll_input_id}/approval` and
  `POST /exceptions/{exception_id}/waiver`: submit audit-commented HR actions.
- `POST /exports` and `GET /exports/{export_id}`: request the backend-gated
  export and retrieve confirmed export details.

Approval, waiver, and export payloads follow the backend models documented in
[`../docs/API.md`](../docs/API.md). The frontend only displays a released
export after the API confirms `status: "RELEASED"`. A `409` response is shown
with its backend-provided blocking reasons.

The current backend does not persist a dedicated recommended-next-step field.
The exceptions view shows the actual event message and evidence, indicates
whether the associated rule is blocking, and offers only the supported waiver
action for open/acknowledged blocking findings. It does not invent remediation
advice.
