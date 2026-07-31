# Run pepper_main.py with Python 2.7 without changing the system PATH.
# Usage: .\run_pepper_controller.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $scriptDir

# pepper_main.py prints UTF-8 bytes under Python 2.
& chcp.com 65001 *> $null
[Console]::InputEncoding = New-Object Text.UTF8Encoding $false
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false

$candidates = @(
    @{ Exe = (Join-Path $scriptDir ".venv-py2\Scripts\python.exe"); Args = @() },
    @{ Exe = "C:\Python27\python.exe"; Args = @() },
    @{ Exe = "C:\Python27-x64\python.exe"; Args = @() },
    @{ Exe = "python2"; Args = @() },
    @{ Exe = "python2.7"; Args = @() },
    @{ Exe = "py"; Args = @("-2.7") },
    @{ Exe = "python"; Args = @() }
)

$python2 = $null
foreach ($candidate in $candidates) {
    $exe = $candidate.Exe
    if ([IO.Path]::IsPathRooted($exe)) {
        if (-not (Test-Path -LiteralPath $exe)) { continue }
    } elseif (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        continue
    }

    try {
        $major = (& $exe @($candidate.Args) -c "import sys; print(sys.version_info[0])" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $major.ToString().Trim() -eq "2") {
            $python2 = $candidate
            break
        }
    } catch { }
}

if (-not $python2) {
    throw "Python 2.7 was not found. Install Python 2.7 x64 and try again."
}

Write-Host "Python 2: $($python2.Exe) $($python2.Args -join ' ')"

& $python2.Exe @($python2.Args) ".\naoqi_path.py"
if ($LASTEXITCODE -ne 0) {
    throw @"
Python 2 cannot import qi. Either run setup for .venv-py2 or extract the
Python 2.7 x64 pynaoqi SDK so this file exists:
  SDK_pynaoqi\pynaoqi\lib\_qi.pyd

The existing SDK_pynaoqi\linux64\...\_qi.so works only on Linux.
"@
}

& $python2.Exe @($python2.Args) ".\pepper_main.py"
exit $LASTEXITCODE
