# Run Gemini listener with the project .venv (Python 3.11+).
# Usage: .\bin\launchers\run_listener.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
Set-Location -LiteralPath $projectRoot

$venvPy = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "Missing .venv - run: .\bin\setup\setup.ps1"
}

& $venvPy (Join-Path $projectRoot "listener_gemini_live.py")
