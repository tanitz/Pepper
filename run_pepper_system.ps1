# Opens the Pepper controller and Gemini listener in separate PowerShell windows.
# Run from PowerShell: .\run_pepper_system.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $scriptDir

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 2.7 command was not found. Install Python 2.7, then try again."
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher (py.exe) was not found. Install Python 3, then try again."
}

$python2Major = (& python -c "import sys; print(sys.version_info[0])").Trim()
if ($LASTEXITCODE -ne 0 -or $python2Major -ne "2") {
    throw "pepper_main.py requires Python 2.7. The 'python' command in this folder is not Python 2."
}

$python3Major = (& py -3 -c "import sys; print(sys.version_info[0])").Trim()
if ($LASTEXITCODE -ne 0 -or $python3Major -ne "3") {
    throw "listener_gemini_live.py requires a working Python 3 installation."
}

function Start-PepperWindow {
    param(
        [string]$Title,
        [string]$PythonCommand,
        [string]$PythonArgument,
        [string]$ScriptName
    )

    # Encode the child command so paths containing spaces or Thai characters
    # remain valid when PowerShell opens the new window.
    $escapedDir = $scriptDir.Replace("'", "''")
    $command = @"
Set-Location -LiteralPath '$escapedDir'
`$Host.UI.RawUI.WindowTitle = '$Title'
& $PythonCommand $PythonArgument .\$ScriptName
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

Start-PepperWindow -Title "Pepper Controller - Python 2" -PythonCommand "python" -PythonArgument "" -ScriptName "pepper_main.py"
Start-Sleep -Seconds 2
Start-PepperWindow -Title "Gemini Listener - Python 3" -PythonCommand "py" -PythonArgument "-3" -ScriptName "listener_gemini_live.py"

Write-Host "Started Pepper Controller and Gemini Listener in separate windows."
