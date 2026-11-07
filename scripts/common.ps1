function Import-PayGateEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $envPath = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        throw "Configuration file not found: $envPath. Run .\scripts\setup.ps1 first."
    }

    $allowedNames = @(
        "SEED",
        "DB_PATH",
        "GROUND_TRUTH_DIR",
        "PAYGATE_EMPLOYEE_COUNT",
        "PAYGATE_PAY_PERIODS",
        "PAYGATE_CORS_ORIGINS"
    )
    foreach ($line in Get-Content -LiteralPath $envPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -notmatch "^([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            throw "Invalid .env entry: $trimmed"
        }

        $name = $Matches[1]
        if ($name -notin $allowedNames) {
            throw "Unsupported .env setting '$name'. See .env.example."
        }
        $value = $Matches[2].Trim()
        if (
            $value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'")))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

function Resolve-PayGatePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue,
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath(
        [System.IO.Path]::Combine($ProjectRoot, $PathValue)
    )
}
