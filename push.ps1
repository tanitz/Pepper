# push.ps1 — sync โค้ดขึ้น GitHub
# วิธีใช้: .\push.ps1 หรือ .\push.ps1 "ข้อความ commit"

param([string]$msg = "")

Set-Location $PSScriptRoot

Write-Host "=== Pull latest ===" -ForegroundColor Cyan
git pull origin main
if ($LASTEXITCODE -ne 0) { Write-Host "Pull failed" -ForegroundColor Red; exit 1 }

Write-Host "`n=== Changed files ===" -ForegroundColor Cyan
git status --short

$files = @(
    "listener_gemini_live.py",
    "pepper_main_py2.py",
    "system_prompt.txt",
    "config.example.json",
    "run_listener.ps1",
    "README.md",
    ".gitignore",
    "push.ps1"
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
    Write-Host "`nไม่มีการเปลี่ยนแปลง" -ForegroundColor Yellow
    exit 0
}

if (-not $msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    $msg = "Update $timestamp"
}

Write-Host "`n=== Commit: $msg ===" -ForegroundColor Cyan
git commit -m $msg

Write-Host "`n=== Push ===" -ForegroundColor Cyan
git push origin main
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nPush สำเร็จ!" -ForegroundColor Green
} else {
    Write-Host "`nPush ล้มเหลว" -ForegroundColor Red
}
