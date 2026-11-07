param(
    [ValidateRange(1, 65535)]
    [int]$Port = 5173
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
)
$frontendRoot = Join-Path $projectRoot "frontend"
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules") -PathType Container)) {
    throw "Frontend dependencies are not installed. Run .\scripts\setup.ps1 first."
}

Set-Location -LiteralPath $frontendRoot
$npmCommand = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    throw "npm was not found. Install Node.js 18 or newer and rerun setup."
}
& $npmCommand.Source run dev -- --host 127.0.0.1 --port $Port --strictPort
if ($LASTEXITCODE -ne 0) {
    throw "Vite stopped with exit code $LASTEXITCODE."
}
