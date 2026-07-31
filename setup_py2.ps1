# Create an isolated Python 2.7 environment for pepper_main.py.
# Usage: .\setup_py2.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $scriptDir

$py3 = Join-Path $scriptDir ".venv\Scripts\python.exe"
$py2Env = Join-Path $scriptDir ".venv-py2"
$py2EnvExe = Join-Path $py2Env "Scripts\python.exe"
$requirements = Join-Path $scriptDir "requirements-py2.txt"

if (-not (Test-Path -LiteralPath $py3)) {
    throw "Missing .venv - run .\setup.ps1 first."
}

$hostPython2 = $null
foreach ($path in @("C:\Python27\python.exe", "C:\Python27-x64\python.exe")) {
    if (Test-Path -LiteralPath $path) {
        $hostPython2 = $path
        break
    }
}
if (-not $hostPython2) {
    foreach ($command in @("python2", "python2.7")) {
        if (Get-Command $command -ErrorAction SilentlyContinue) {
            $major = (& $command -c "import sys; print(sys.version_info[0])").Trim()
            if ($LASTEXITCODE -eq 0 -and $major -eq "2") {
                $hostPython2 = $command
                break
            }
        }
    }
}
if (-not $hostPython2) {
    throw "Python 2.7 x64 was not found."
}

& $py3 -m virtualenv --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing virtualenv 20.21.1 into the Python 3 tooling env..."
    & $py3 -m pip install "virtualenv==20.21.1"
    if ($LASTEXITCODE -ne 0) { throw "Could not install virtualenv." }
}

if (-not (Test-Path -LiteralPath $py2EnvExe)) {
    Write-Host "Creating .venv-py2 with $hostPython2 ..."
    & $py3 -m virtualenv --python $hostPython2 $py2Env
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv-py2." }
}

Write-Host "Installing Python 2 requirements..."
& $py2EnvExe -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw "Could not install Python 2 requirements." }

& $py2EnvExe -c "import qi; print('Python 2 qi OK: %s' % qi.__file__)"
if ($LASTEXITCODE -ne 0) { throw "Python 2 qi import failed." }

Write-Host ""
Write-Host "Python 2 environment is ready."
Write-Host "Run controller: .\run_pepper_controller.ps1"
Write-Host "Run both:       .\run_pepper_system.ps1"
