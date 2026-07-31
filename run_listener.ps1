# Run Gemini listener with the project .venv (Python 3.11+).
# Usage: .\run_listener.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $scriptDir

$venvPy = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "Missing .venv — run: .\setup.ps1"
}

& $venvPy ".\listener_gemini_live.py"
