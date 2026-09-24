$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Create .venv and install requirements first; see UNIVERSAL_TESTING.md.'
}
$env:DEEPEVAL_TELEMETRY_OPT_OUT = 'YES'
& $projectPython -m uvicorn evo_platform.server:app --host 127.0.0.1 --port 8080
