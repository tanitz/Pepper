# Pepper - Windows setup (venv + deps + readiness). Mirrors Makefile targets.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 check
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 setup-model

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "help", "setup", "setup-venv", "install", "install-cuda",
        "check", "status", "ready", "doctor",
        "setup-config", "setup-model", "run-listener", "clean-venv"
    )]
    [string]$Target = "setup"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$VenvDir = Join-Path $Root ".venv"
$VenvPy  = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"
$Req     = Join-Path $Root "requirements.txt"
$ReqCuda = Join-Path $Root "requirements-cuda.txt"

function Write-Ok([string]$Message)   { Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Fail([string]$Message) { Write-Host "  [FAIL] $Message" -ForegroundColor Red }
function Write-Warn([string]$Message) { Write-Host "  [WARN] $Message" -ForegroundColor Yellow }

function Show-Help {
    Write-Host @"
Pepper setup.ps1 (Windows venv)

  .\setup.ps1                Create .venv, install deps, bootstrap config
  .\setup.ps1 setup-venv     Create .venv with Python 3.11 only
  .\setup.ps1 install        pip install -r requirements.txt into .venv
  .\setup.ps1 install-cuda   Optional NVIDIA CUDA libs (GPU Whisper)
  .\setup.ps1 check          READY / NOT READY report
  .\setup.ps1 setup-config   Create config\config.json from example if missing
  .\setup.ps1 setup-model    Download Thonburian Whisper CT2 model (~3.1 GB)
  .\setup.ps1 run-listener   Run listener_gemini_live.py with .venv
  .\setup.ps1 clean-venv     Remove .venv

Typical flow:
  1) .\setup.ps1
  2) edit config\config.json  (gemini_api_key)
  3) .\setup.ps1 setup-model
  4) place Windows NAOqi under SDK_pynaoqi\pynaoqi\lib\  (_qi.pyd + dlls)
  5) .\setup.ps1 check
  6) .\run_pepper_system.ps1   (or .\setup.ps1 run-listener)

If scripts are blocked:
  powershell -ExecutionPolicy Bypass -File .\setup.ps1

Activate manually:
  .\.venv\Scripts\Activate.ps1
"@
}

function Resolve-HostPython {
    # Prefer newest available 3.11-3.14 (pygame-ce + sounddevice support 3.14).
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($arg in @("-3.14", "-3.13", "-3.12", "-3.11", "-3")) {
            try {
                $ver = & py $arg -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    $parts = $ver.Trim().Split(".")
                    $maj = [int]$parts[0]; $min = [int]$parts[1]
                    if ($maj -eq 3 -and $min -ge 11 -and $min -le 14) {
                        $candidates += @{ Exe = "py"; Args = @($arg); Major = $maj; Minor = $min }
                    }
                }
            } catch { }
        }
    }
    foreach ($name in @("python3.14", "python3.13", "python3.12", "python3.11", "python")) {
        if (Get-Command $name -ErrorAction SilentlyContinue) {
            try {
                $ver = & $name -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    $parts = $ver.Trim().Split(".")
                    $maj = [int]$parts[0]; $min = [int]$parts[1]
                    if ($maj -eq 3 -and $min -ge 11 -and $min -le 14) {
                        $candidates += @{ Exe = $name; Args = @(); Major = $maj; Minor = $min }
                    }
                }
            } catch { }
        }
    }
    if ($candidates.Count -eq 0) { return $null }
    return ($candidates | Sort-Object { $_.Minor } -Descending | Select-Object -First 1)
}

function Ensure-Venv {
    $hostPy = Resolve-HostPython
    if (-not $hostPy) {
        throw @"
Python 3.11-3.14 not found.
Install e.g.:
  winget install Python.Python.3.14
Then:
  powershell -ExecutionPolicy Bypass -File .\setup.ps1 clean-venv
  powershell -ExecutionPolicy Bypass -File .\setup.ps1
"@
    }

    if (Test-Path -LiteralPath $VenvPy) {
        $existing = & $VenvPy -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        $ok = $false
        if ($existing) {
            $parts = $existing.ToString().Trim().Split(".")
            if ($parts.Count -ge 2) {
                $min = [int]$parts[1]
                if ([int]$parts[0] -eq 3 -and $min -ge 11 -and $min -le 14) { $ok = $true }
            }
        }
        if (-not $ok) {
            throw @"
Existing .venv is Python $($existing) but this project needs 3.11-3.14.
Recreate it:
  powershell -ExecutionPolicy Bypass -File .\setup.ps1 clean-venv
  powershell -ExecutionPolicy Bypass -File .\setup.ps1
"@
        }
        Write-Ok "venv already exists: $VenvDir"
    } else {
        $shown = & $hostPy.Exe (@($hostPy.Args) + @("--version")) 2>&1
        Write-Host "==> Creating venv at $VenvDir with $shown"
        & $hostPy.Exe (@($hostPy.Args) + @("-m", "venv", $VenvDir))
        if ($LASTEXITCODE -ne 0) { throw "Failed to create venv" }
    }

    $ver = & $VenvPy --version 2>&1
    Write-Ok "interpreter: $ver"
}

function Install-Requirements {
    Ensure-Venv
    Write-Host "==> Upgrading pip..."
    & $VenvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

    if (-not (Test-Path -LiteralPath $Req)) {
        throw "Missing requirements.txt at $Req"
    }
    Write-Host "==> Installing requirements from $Req ..."
    & $VenvPip install -r $Req
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    Write-Ok "Python 3 packages installed into .venv"
    Write-Host ""
    Write-Host "Tip (Windows audio): mic uses sounddevice (PortAudio). If open fails, check mic permissions in Windows Settings."
}

function Install-Cuda {
    Ensure-Venv
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        Write-Warn "nvidia-smi not found - installing CUDA wheels anyway"
    }
    Write-Host "==> Installing CUDA libs from $ReqCuda ..."
    & $VenvPip install -r $ReqCuda
    if ($LASTEXITCODE -ne 0) { throw "CUDA pip install failed" }
    Write-Ok "CUDA packages installed"
}

function Setup-Config {
    $configDir = Join-Path $Root "config"
    $configPath = Join-Path $configDir "config.json"
    $examplePath = Join-Path $configDir "config.example.json"
    if (-not (Test-Path -LiteralPath $configDir)) {
        New-Item -ItemType Directory -Path $configDir | Out-Null
    }
    if (Test-Path -LiteralPath $configPath) {
        Write-Ok "config\config.json already exists"
    } else {
        if (-not (Test-Path -LiteralPath $examplePath)) {
            throw "Missing config\config.example.json"
        }
        Copy-Item -LiteralPath $examplePath -Destination $configPath
        Write-Ok "created config\config.json - set gemini_api_key"
    }
}

function Setup-Model {
    Ensure-Venv
    $modelDir = Join-Path $Root "model\thonburian-large-ct2"
    $modelBin = Join-Path $modelDir "model.bin"
    $safeTensors = Join-Path $modelDir "model.safetensors"

    Write-Host "==> Downloading Thonburian Whisper CT2 (~3.1 GB)..."
    if (-not (Test-Path -LiteralPath $modelBin) -and (Test-Path -LiteralPath $safeTensors)) {
        Write-Host "==> Removing incompatible Transformers checkpoint..."
        Remove-Item -LiteralPath $safeTensors -Force
    }

    $modelDirPy = $modelDir.Replace("\", "/")
    $tmpPy = Join-Path $env:TEMP "pepper_download_model.py"
    @"
from huggingface_hub import snapshot_download
snapshot_download(
    "CodeHardThailand/whisper-th-large-v3-combined-ct2",
    local_dir=r"$modelDirPy",
)
"@ | Set-Content -LiteralPath $tmpPy -Encoding ASCII

    try {
        & $VenvPy $tmpPy
        if ($LASTEXITCODE -ne 0) { throw "model download failed" }
    } finally {
        Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path -LiteralPath $modelBin)) {
        throw "model.bin still missing after download"
    }
    Write-Ok "model.bin ready"
}

function Test-GeminiKeyStatus {
    param([string]$ConfigPath)
    $configPathPy = $ConfigPath.Replace("\", "/")
    $tmpPy = Join-Path $env:TEMP "pepper_check_key.py"
    @"
import json
from pathlib import Path
p = Path(r"$configPathPy")
try:
    c = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    print("invalid")
    raise SystemExit
k = (c.get("gemini_api_key") or "").strip()
bad = ("", "YOUR_GEMINI_API_KEY")
if (not k) or (k in bad) or ("YOUR_" in k.upper()) or (len(k) < 20):
    print("placeholder")
else:
    print("ok")
"@ | Set-Content -LiteralPath $tmpPy -Encoding ASCII

    try {
        $out = & $VenvPy $tmpPy 2>$null
        if ($out) { return ([string]$out).Trim() }
        return "placeholder"
    } finally {
        Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue
    }
}

function Test-PythonImport {
    param([string]$ModuleName)
    # FutureWarning on stderr must not abort under $ErrorActionPreference = Stop
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $null = & $VenvPy -c "import $ModuleName" 2>&1
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Invoke-Check {
    $script:CheckPass = 0
    $script:CheckFail = 0
    $script:CheckWarn = 0

    function Ok([string]$m)   { $script:CheckPass++; Write-Ok $m }
    function Fail([string]$m) { $script:CheckFail++; Write-Fail $m }
    function Warn([string]$m) { $script:CheckWarn++; Write-Warn $m }

    Write-Host "Pepper readiness check"
    Write-Host "  workspace: $Root"
    Write-Host "  host:      Windows"
    Write-Host ""

    Write-Host "== Python 3 / venv =="
    if (Test-Path -LiteralPath $VenvPy) {
        $ver = & $VenvPy --version 2>&1
        Ok "venv python: $VenvPy ($ver)"
    } else {
        Fail "missing .venv - run: .\setup.ps1"
    }
    Write-Host ""

    Write-Host "== Python 2 (pepper_main / NAOqi) =="
    $py2 = $null
    if (Get-Command python -ErrorAction SilentlyContinue) {
        try {
            $maj = (& python -c "import sys; print(sys.version_info[0])" 2>$null)
            if ($maj -and $maj.ToString().Trim() -eq "2") { $py2 = "python" }
        } catch { }
    }
    if ($py2) {
        $ver2 = & python --version 2>&1
        Ok "Python 2 available: python ($ver2)"
    } else {
        Warn "Python 2.7 not on PATH - needed for pepper_main.py + Windows NAOqi"
    }
    Write-Host ""

    Write-Host "== App assets =="
    $qiLib = Join-Path $Root "SDK_pynaoqi\pynaoqi\lib"
    $qiGlob = @()
    if (Test-Path -LiteralPath $qiLib) {
        $qiGlob = @(Get-ChildItem -Path $qiLib -Filter "_qi*.pyd" -ErrorAction SilentlyContinue)
    }
    if ($qiGlob.Count -gt 0) {
        Ok "NAOqi Windows SDK present ($($qiGlob[0].FullName))"
        if ($py2) {
            try {
                $sdkPath = (& python naoqi_path.py 2>$null)
                if ($LASTEXITCODE -eq 0 -and $sdkPath) {
                    Ok "naoqi_path.py resolves: $($sdkPath.ToString().Trim())"
                } else {
                    Fail "naoqi_path.py cannot resolve SDK"
                }
            } catch {
                Fail "naoqi_path.py cannot resolve SDK"
            }
        }
    } else {
        Fail "NAOqi Windows SDK missing - extract to SDK_pynaoqi\pynaoqi\lib\ (_qi.pyd + dlls)"
    }

    $modelBin = Join-Path $Root "model\thonburian-large-ct2\model.bin"
    if (Test-Path -LiteralPath $modelBin) {
        Ok "Whisper model present ($modelBin)"
    } else {
        Fail "Whisper model.bin missing - download with: .\setup.ps1 setup-model"
    }

    $configPath = Join-Path $Root "config\config.json"
    if (Test-Path -LiteralPath $configPath) {
        Ok "config\config.json exists"
        if (Test-Path -LiteralPath $VenvPy) {
            $keyStatus = Test-GeminiKeyStatus -ConfigPath $configPath
            if ($keyStatus -eq "ok") {
                Ok "gemini_api_key looks set"
            } elseif ($keyStatus -eq "invalid") {
                Fail "config\config.json is not valid JSON"
            } else {
                Fail "gemini_api_key not set - edit config\config.json"
            }
        }
    } else {
        Fail "config\config.json missing - run: .\setup.ps1 setup-config"
    }

    $mainPy = Join-Path $Root "pepper_main.py"
    $listenerPy = Join-Path $Root "listener_gemini_live.py"
    if ((Test-Path -LiteralPath $mainPy) -and (Test-Path -LiteralPath $listenerPy)) {
        Ok "Main entrypoints present (pepper_main.py, listener_gemini_live.py)"
    } else {
        Fail "Missing pepper_main.py or listener_gemini_live.py"
    }
    Write-Host ""

    Write-Host "== Python 3 packages =="
    if (Test-Path -LiteralPath $VenvPy) {
        foreach ($pkg in @("faster_whisper", "google.generativeai", "sounddevice", "pygame", "numpy", "scipy")) {
            if (Test-PythonImport $pkg) { Ok "import $pkg" }
            else { Fail "cannot import $pkg - run: .\setup.ps1 install" }
        }
        if (Test-PythonImport "ctranslate2") {
            Ok "import ctranslate2"
            $prev = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                $cudaN = & $VenvPy -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())" 2>&1 |
                    Where-Object { $_ -match '^\d+$' } |
                    Select-Object -Last 1
            } finally {
                $ErrorActionPreference = $prev
            }
            $cudaCount = 0
            if ($cudaN) { [void][int]::TryParse($cudaN.ToString().Trim(), [ref]$cudaCount) }
            if ($cudaCount -gt 0) {
                Ok "CUDA devices: $cudaCount (Whisper will use GPU)"
            } else {
                Warn "CUDA devices: 0 - Whisper will use CPU (GPU: .\setup.ps1 install-cuda)"
            }
        } else {
            Fail "cannot import ctranslate2 - run: .\setup.ps1 install"
        }
    } else {
        Fail "skip package imports - create venv with: .\setup.ps1"
    }
    Write-Host ""

    Write-Host "----------------------------------------"
    Write-Host "  OK=$script:CheckPass  WARN=$script:CheckWarn  FAIL=$script:CheckFail"
    if ($script:CheckFail -eq 0) {
        Write-Host "  STATUS: READY to run" -ForegroundColor Green
        Write-Host "    .\run_pepper_system.ps1"
        Write-Host "    # or: .\setup.ps1 run-listener"
        exit 0
    } else {
        Write-Host "  STATUS: NOT READY" -ForegroundColor Red
        Write-Host "  Fix FAIL items above, then re-run: .\setup.ps1 check"
        exit 1
    }
}

function Run-Listener {
    Ensure-Venv
    if (-not (Test-Path -LiteralPath $VenvPy)) {
        throw "missing .venv - run: .\setup.ps1"
    }
    & $VenvPy (Join-Path $Root "listener_gemini_live.py")
}

function Clean-Venv {
    if (Test-Path -LiteralPath $VenvDir) {
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
        Write-Ok "removed $VenvDir"
    } else {
        Write-Ok "no .venv to remove"
    }
}

function Invoke-Setup {
    Ensure-Venv
    Install-Requirements
    Setup-Config
    Write-Host ""
    Write-Host "Setup finished."
    Write-Host "  Optional: .\setup.ps1 setup-model"
    Write-Host "  Place Windows NAOqi at: SDK_pynaoqi\pynaoqi\lib\  (_qi.pyd)"
    Write-Host "  Optional GPU: .\setup.ps1 install-cuda"
    Write-Host "  Then: .\setup.ps1 check"
    Write-Host "  Run:  .\run_pepper_system.ps1"
    Write-Host "  Or:   .\.venv\Scripts\Activate.ps1"
}

switch ($Target) {
    "help"          { Show-Help }
    "setup"         { Invoke-Setup }
    "setup-venv"    { Ensure-Venv }
    "install"       { Install-Requirements }
    "install-cuda"  { Install-Cuda }
    "setup-config"  { Setup-Config }
    "setup-model"   { Setup-Model }
    "check"         { Invoke-Check }
    "status"        { Invoke-Check }
    "ready"         { Invoke-Check }
    "doctor"        { Invoke-Check }
    "run-listener"  { Run-Listener }
    "clean-venv"    { Clean-Venv }
}
