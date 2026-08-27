# Opens the Pepper controller and Gemini listener in separate PowerShell windows.
# Run from PowerShell: .\bin\launchers\run_pepper_system.ps1
# Prereq: .\bin\setup\setup.ps1 and .\bin\setup\setup_py2.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
Set-Location -LiteralPath $projectRoot

$venvPy = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "Missing .venv - run: .\bin\setup\setup.ps1"
}

function Resolve-Python2 {
    $candidates = @(
        @{ Exe = (Join-Path $projectRoot ".venv-py2\Scripts\python.exe"); Args = @() },
        @{ Exe = "C:\Python27\python.exe"; Args = @() },
        @{ Exe = "C:\Python27-x64\python.exe"; Args = @() },
        @{ Exe = "python2"; Args = @() },
        @{ Exe = "python2.7"; Args = @() },
        @{ Exe = "py"; Args = @("-2.7") },
        @{ Exe = "python"; Args = @() }
    )

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
                return [PSCustomObject]@{
                    Exe  = $exe
                    Args = @($candidate.Args)
                }
            }
        } catch { }
    }
    return $null
}

$python2 = Resolve-Python2
if (-not $python2) {
    throw "Python 2.7 was not found. Install Python 2.7 x64 for pepper_main.py."
}

# Fail before opening child windows if the Windows NAOqi native module is absent.
& $python2.Exe @($python2.Args) ".\naoqi_path.py" *> $null
if ($LASTEXITCODE -ne 0) {
    throw @"
Python 2 cannot import qi. Either run setup for .venv-py2 or extract the
Python 2.7 x64 pynaoqi SDK so this file exists:
  SDK_pynaoqi\pynaoqi\lib\_qi.pyd

The existing SDK_pynaoqi\linux64\...\_qi.so works only on Linux.
"@
}

function Start-PepperWindow {
    param(
        [string]$Title,
        [string]$PythonExe,
        [string[]]$PythonArgs = @(),
        [string]$ScriptName
    )

    # Encode the child command so paths containing spaces or Thai characters
    # remain valid when PowerShell opens the new window.
    $escapedDir = $projectRoot.Replace("'", "''")
    $escapedPy  = $PythonExe.Replace("'", "''")
    $argList = ($PythonArgs | ForEach-Object { "'$($_ -replace "'", "''")'" }) -join ", "
    if (-not $argList) { $argList = "" }

$command = @"
Set-Location -LiteralPath '$escapedDir'
`$Host.UI.RawUI.WindowTitle = '$Title'
& chcp.com 65001 *> `$null
`[Console`]::InputEncoding = New-Object Text.UTF8Encoding `$false
`[Console`]::OutputEncoding = New-Object Text.UTF8Encoding `$false
`$py = '$escapedPy'
`$pyArgs = @($argList)
& `$py @`$pyArgs .\$ScriptName
"@
    $encodedCommand = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($command)
    )

    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-EncodedCommand", $encodedCommand
    )
}

Start-PepperWindow -Title "Pepper Controller - Python 2" -PythonExe $python2.Exe -PythonArgs $python2.Args -ScriptName "pepper_main.py"
Start-Sleep -Seconds 2
Start-PepperWindow -Title "Gemini Listener - Python 3" -PythonExe $venvPy -ScriptName "listener_gemini_live.py"

Write-Host "Started Pepper Controller and Gemini Listener in separate windows."
Write-Host "  Controller: $($python2.Exe) $($python2.Args -join ' ') pepper_main.py"
Write-Host "  Listener:   $venvPy listener_gemini_live.py"
