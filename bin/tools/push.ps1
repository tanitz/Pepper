# Sync project code to GitHub.
# Usage: .\bin\tools\push.ps1 or pass a commit message as the first argument.

param([string]$msg = "")

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $projectRoot

Write-Host "=== Pull latest ===" -ForegroundColor Cyan
git pull origin develop
if ($LASTEXITCODE -ne 0) { Write-Host "Pull failed" -ForegroundColor Red; exit 1 }

Write-Host "`n=== Changed files ===" -ForegroundColor Cyan
git status --short

$files = @(
    "listener_gemini_live.py",
    "pepper_main.py",
    "pepper_ui.html",
    "pepper_speak.html",
    "naoqi_path.py",
    "config",
    "bin",
    "README.md",
    ".gitignore",
    "requirements.txt",
    "requirements-cuda.txt",
    "requirements-py2.txt"
)

$changed = $false
foreach ($f in $files) {
    if (Test-Path $f) {
        $result = git diff --name-only HEAD -- $f
        if ($result -or (git ls-files --others --exclude-standard -- $f)) {
            git add $f
            $changed = $true
        }
    }
}

if (-not $changed) {
    Write-Host "`nNo changes found." -ForegroundColor Yellow
    exit 0
}

if (-not $msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    $msg = "Update $timestamp"
}

Write-Host "`n=== Commit: $msg ===" -ForegroundColor Cyan
git commit -m $msg

Write-Host "`n=== Push ===" -ForegroundColor Cyan
git push origin develop
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nPush completed." -ForegroundColor Green
} else {
    Write-Host "`nPush failed." -ForegroundColor Red
}
