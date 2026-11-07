$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
)
Set-Location -LiteralPath $projectRoot
. (Join-Path $PSScriptRoot "common.ps1")

$envPath = Join-Path $projectRoot ".env"
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".env.example") -Destination $envPath
    Write-Output "Created .env from .env.example."
}
Import-PayGateEnvironment -ProjectRoot $projectRoot

if (-not $env:DB_PATH -or -not $env:GROUND_TRUTH_DIR) {
    throw ".env must define DB_PATH and GROUND_TRUTH_DIR."
}
$databasePath = Resolve-PayGatePath -PathValue $env:DB_PATH -ProjectRoot $projectRoot
$datasetRoot = [System.IO.Path]::GetDirectoryName($databasePath)
$groundTruthPath = Resolve-PayGatePath `
    -PathValue $env:GROUND_TRUTH_DIR `
    -ProjectRoot $projectRoot
$expectedGroundTruthPath = [System.IO.Path]::GetFullPath(
    (Join-Path $datasetRoot "ground_truth")
)
if (
    [System.IO.Path]::GetFileName($databasePath) -ne "paygate.db" -or
    $groundTruthPath -ne $expectedGroundTruthPath
) {
    throw @"
Automatic starter setup expects DB_PATH to end in paygate.db and
GROUND_TRUTH_DIR to be the sibling ground_truth directory. Update .env to use
the defaults in .env.example, or generate and configure a custom dataset
separately.
"@
}

$manifestPath = Join-Path $datasetRoot "manifest.json"
$labelsPath = Join-Path $groundTruthPath "labels.csv"
$datasetFiles = @($databasePath, $manifestPath, $labelsPath)
$datasetExists = Test-Path -LiteralPath $datasetRoot
if ($datasetExists) {
    $existingDatasetFiles = @(
        $datasetFiles | Where-Object {
            Test-Path -LiteralPath $_ -PathType Leaf
        }
    )
    if ($existingDatasetFiles.Count -ne $datasetFiles.Count) {
        throw "Dataset directory already exists but is incomplete: $datasetRoot. No files were changed; choose another DB_PATH or inspect this directory."
    }
}

$requiredSeedFiles = @(
    "data\seed\pay_groups.csv",
    "data\seed\allowance_types.csv",
    "data\seed\deduction_types.csv"
)
foreach ($relativePath in $requiredSeedFiles) {
    $seedPath = Join-Path $projectRoot $relativePath
    if (-not (Test-Path -LiteralPath $seedPath -PathType Leaf)) {
        throw "Required generator input is missing: $seedPath"
    }
}

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pythonLauncher) {
    $basePython = $pythonLauncher.Source
    $pythonSelector = @("-3.12")
    & $basePython @pythonSelector -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $pythonSelector = @("-3")
        & $basePython @pythonSelector -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" | Out-Null
    }
}
else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python 3.10 or newer was not found. Install Python 3.12 and enable the Windows Python launcher."
    }
    $basePython = $pythonCommand.Source
    $pythonSelector = @()
    & $basePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" | Out-Null
}
if ($LASTEXITCODE -ne 0) {
    throw "Could not start Python. Install Python 3.12 and retry."
}
$pythonVersionText = (& $basePython @pythonSelector -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
$pythonVersion = [version]$pythonVersionText
if ($pythonVersion -lt [version]"3.10") {
    throw "Python 3.10 or newer is required; found $pythonVersionText."
}
Write-Output "Using Python $pythonVersionText."

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm -ErrorAction SilentlyContinue
if (-not $nodeCommand -or -not $npmCommand) {
    throw "Node.js 18 or newer and npm were not found. Install Node.js 20 LTS and retry."
}
$nodeVersionText = (& $nodeCommand.Source --version).Trim()
if ($LASTEXITCODE -ne 0 -or $nodeVersionText -notmatch "^v?(\d+)\.") {
    throw "Could not determine the installed Node.js version."
}
if ([int]$Matches[1] -lt 18) {
    throw "Node.js 18 or newer is required; found $nodeVersionText."
}
Write-Output "Using Node.js $nodeVersionText."

$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    if (Test-Path -LiteralPath $venvPath) {
        throw "The existing .venv is incomplete. Inspect or rename it before retrying setup."
    }
    & $basePython @pythonSelector -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python virtual environment creation failed."
    }
}
$venvPythonVersionText = (& $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
if ($LASTEXITCODE -ne 0 -or [version]$venvPythonVersionText -lt [version]"3.10") {
    throw "The project virtual environment must use Python 3.10 or newer; found '$venvPythonVersionText'."
}

& $venvPython -m pip install -r (Join-Path $projectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Backend dependency installation failed."
}

Push-Location (Join-Path $projectRoot "frontend")
try {
    & $npmCommand.Source ci
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend dependency installation failed."
    }
}
finally {
    Pop-Location
}

if ($datasetExists) {
    & $venvPython (Join-Path $projectRoot "scripts\validate_data.py") $datasetRoot --no-report
    if ($LASTEXITCODE -ne 0) {
        throw "The existing starter dataset failed validation. It was not overwritten."
    }
    Write-Output "Existing starter dataset is complete and valid; it was not overwritten."
}
else {
    $dataParent = Split-Path -Parent $datasetRoot
    New-Item -ItemType Directory -Path $dataParent -Force | Out-Null
    $stageName = ".paygate-starter-setup-$([guid]::NewGuid().ToString('N'))"
    $stageRoot = Join-Path $dataParent $stageName
    New-Item -ItemType Directory -Path $stageRoot | Out-Null
    try {
        $env:SEED = "20261022"
        & $venvPython -m backend.generator `
            --employees 200 `
            --seed 20261022 `
            --out $stageRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Starter dataset generation failed."
        }

        foreach ($requiredPath in @(
            (Join-Path $stageRoot "paygate.db"),
            (Join-Path $stageRoot "manifest.json"),
            (Join-Path $stageRoot "ground_truth\labels.csv")
        )) {
            if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
                throw "Dataset generation did not create required file: $requiredPath"
            }
        }

        & $venvPython (Join-Path $projectRoot "scripts\validate_data.py") $stageRoot --no-report
        if ($LASTEXITCODE -ne 0) {
            throw "Generated starter dataset failed validation."
        }
        if (Test-Path -LiteralPath $datasetRoot) {
            throw "Dataset target appeared during setup; refusing to overwrite: $datasetRoot"
        }
        [System.IO.Directory]::Move($stageRoot, $datasetRoot)
        Write-Output "Created validated starter database and ground-truth labels at $datasetRoot."
    }
    finally {
        if (Test-Path -LiteralPath $stageRoot) {
            $resolvedStage = [System.IO.Path]::GetFullPath($stageRoot)
            $resolvedParent = [System.IO.Path]::GetFullPath($dataParent)
            if (
                $resolvedStage.StartsWith(
                    $resolvedParent + [System.IO.Path]::DirectorySeparatorChar,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -and
                [System.IO.Path]::GetFileName($resolvedStage).StartsWith(
                    ".paygate-starter-setup-",
                    [System.StringComparison]::Ordinal
                )
            ) {
                Remove-Item -LiteralPath $resolvedStage -Recurse -Force
            }
        }
    }
}

Write-Output "PayGate setup completed."
Write-Output "Start the API with .\scripts\start-backend.ps1"
Write-Output "Start the dashboard in another terminal with .\scripts\start-frontend.ps1"
