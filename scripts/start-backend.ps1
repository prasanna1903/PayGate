$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
)
Set-Location -LiteralPath $projectRoot
. (Join-Path $PSScriptRoot "common.ps1")
Import-PayGateEnvironment -ProjectRoot $projectRoot

$databasePath = Resolve-PayGatePath -PathValue $env:DB_PATH -ProjectRoot $projectRoot
$groundTruthPath = Resolve-PayGatePath `
    -PathValue $env:GROUND_TRUTH_DIR `
    -ProjectRoot $projectRoot
if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
    throw "Database not found: $databasePath. Run .\scripts\setup.ps1 first."
}
if (-not (Test-Path -LiteralPath (Join-Path $groundTruthPath "labels.csv") -PathType Leaf)) {
    throw "Ground-truth labels not found under $groundTruthPath. Run .\scripts\setup.ps1 first."
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "Project virtual environment not found. Run .\scripts\setup.ps1 first."
}
$env:DB_PATH = $databasePath
$env:GROUND_TRUTH_DIR = $groundTruthPath
& $venvPython -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000 --reload
if ($LASTEXITCODE -ne 0) {
    throw "FastAPI stopped with exit code $LASTEXITCODE."
}
