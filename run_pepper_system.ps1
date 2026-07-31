# Opens the Pepper controller and Gemini listener in separate PowerShell windows.
# Run from PowerShell: .\run_pepper_system.ps1
# Prereq: .\setup.ps1  (+ Windows NAOqi under SDK_pynaoqi\pynaoqi\lib\)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $scriptDir

$venvPy = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "Missing .venv — run: .\setup.ps1"
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 2.7 command was not found. Install Python 2.7 for pepper_main.py, then try again."
}

$python2Major = (& python -c "import sys; print(sys.version_info[0])").Trim()
if ($LASTEXITCODE -ne 0 -or $python2Major -ne "2") {
    throw "pepper_main.py requires Python 2.7. The 'python' command in this folder is not Python 2."
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
    $escapedDir = $scriptDir.Replace("'", "''")
    $escapedPy  = $PythonExe.Replace("'", "''")
    $argList = ($PythonArgs | ForEach-Object { "'$($_ -replace "'", "''")'" }) -join ", "
    if (-not $argList) { $argList = "" }

    $command = @"
Set-Location -LiteralPath '$escapedDir'
`$Host.UI.RawUI.WindowTitle = '$Title'
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

Start-PepperWindow -Title "Pepper Controller - Python 2" -PythonExe "python" -ScriptName "pepper_main.py"
Start-Sleep -Seconds 2
Start-PepperWindow -Title "Gemini Listener - Python 3" -PythonExe $venvPy -ScriptName "listener_gemini_live.py"

Write-Host "Started Pepper Controller and Gemini Listener in separate windows."
Write-Host "  Controller: python pepper_main.py"
Write-Host "  Listener:   $venvPy listener_gemini_live.py"
