$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$activePython = if ($env:VIRTUAL_ENV) {
    Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
} else {
    $null
}

$exitCode = 1
Push-Location $projectRoot
try {
    if ($activePython -and (Test-Path -LiteralPath $activePython)) {
        & $activePython -m backend.launcher @args
    } elseif (Test-Path -LiteralPath $projectPython) {
        & $projectPython -m backend.launcher @args
    } else {
        & uv run --frozen python -m backend.launcher @args
    }
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

exit $exitCode
