#!/usr/bin/env bash
# Report whether Pepper is ready to run (host Docker / Dev Container / app deps).
# Exit 0 = READY, 1 = NOT READY
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
WARN=0

ok()   { PASS=$((PASS + 1)); printf '  [OK]   %s\n' "$*"; }
fail() { FAIL=$((FAIL + 1)); printf '  [FAIL] %s\n' "$*"; }
warn() { WARN=$((WARN + 1)); printf '  [WARN] %s\n' "$*"; }

IN_CONTAINER=0
if [[ -f /.dockerenv ]] || grep -qaE 'docker|containerd|kubepods' /proc/1/cgroup 2>/dev/null; then
  IN_CONTAINER=1
fi

echo "Pepper readiness check"
echo "  workspace: $ROOT"
if [[ "$IN_CONTAINER" -eq 1 ]]; then
  echo "  context:   Dev Container / Docker"
else
  echo "  context:   host (outside container)"
fi
echo ""

# ── Docker / Dev Container scaffolding ──────────────────────────────────────
echo "== Docker / Dev Container =="
if command -v docker >/dev/null 2>&1; then
  ok "docker CLI found: $(command -v docker)"
  if docker info >/dev/null 2>&1; then
    ok "Docker daemon is running"
  else
    DOCKER_ERR="$(docker info 2>&1 | tail -n 1 | tr -d '\r')"
    if [[ "$IN_CONTAINER" -eq 1 ]]; then
      warn "Docker daemon not reachable from inside container (usually fine)"
    elif echo "$DOCKER_ERR" | grep -qi 'permission denied'; then
      fail "Docker socket permission denied — start/open OrbStack or Docker Desktop, then retry"
    else
      fail "Docker daemon not ready — start OrbStack / Docker Desktop (${DOCKER_ERR})"
    fi
  fi
else
  if [[ "$IN_CONTAINER" -eq 1 ]]; then
    warn "docker CLI not installed inside container (not required to run Pepper)"
  else
    fail "docker CLI not found — install Docker Desktop / OrbStack"
  fi
fi

if [[ -f .devcontainer/devcontainer.json && -f .devcontainer/Dockerfile && -f .devcontainer/post-create.sh ]]; then
  ok "Dev Container files present (.devcontainer/)"
else
  fail "Missing .devcontainer files (devcontainer.json / Dockerfile / post-create.sh)"
fi

if [[ "$IN_CONTAINER" -eq 1 ]]; then
  ok "Running inside a container"
else
  warn "Not inside Dev Container yet — use: Dev Containers: Reopen in Container"
fi
echo ""

# ── Runtime toolchain (mostly inside container) ──────────────────────────────
echo "== Runtime =="
if command -v python3.11 >/dev/null 2>&1 || python3 --version 2>/dev/null | grep -q '3\.11'; then
  PY3="$(command -v python3.11 2>/dev/null || command -v python3)"
  ok "Python 3.11 available: $PY3 ($($PY3 --version 2>&1))"
else
  if [[ "$IN_CONTAINER" -eq 1 ]]; then
    fail "Python 3.11 missing inside container"
  else
    warn "Python 3.11 not on host (expected inside Dev Container)"
  fi
fi

if command -v python2 >/dev/null 2>&1 || command -v python2.7 >/dev/null 2>&1; then
  PY2="$(command -v python2 2>/dev/null || command -v python2.7)"
  ok "Python 2.7 available: $PY2 ($($PY2 --version 2>&1))"
else
  if [[ "$IN_CONTAINER" -eq 1 ]]; then
    fail "Python 2.7 missing inside container (needed for pepper_main.py)"
  else
    warn "Python 2.7 not on host (expected inside Dev Container)"
  fi
fi
echo ""

# ── App assets ───────────────────────────────────────────────────────────────
echo "== App assets =="
QI_SO="SDK_pynaoqi/linux64/lib/python2.7/site-packages/_qi.so"
if [[ -f "$QI_SO" ]]; then
  ok "NAOqi Linux SDK present ($QI_SO)"
  if command -v python2 >/dev/null 2>&1 || command -v python2.7 >/dev/null 2>&1; then
    PY2="$(command -v python2 2>/dev/null || command -v python2.7)"
    if SDK_PATH="$($PY2 naoqi_path.py 2>/dev/null)"; then
      ok "naoqi_path.py resolves: $SDK_PATH"
    else
      fail "naoqi_path.py cannot resolve SDK"
    fi
  fi
else
  fail "NAOqi Linux SDK missing — run: make setup-sdk"
fi

MODEL_BIN="model/thonburian-large-ct2/model.bin"
if [[ -f "$MODEL_BIN" ]]; then
  ok "Whisper model present ($MODEL_BIN)"
else
  fail "Whisper model.bin missing — download with: make setup-model"
fi

CONFIG="config/config.json"
if [[ -f "$CONFIG" ]]; then
  ok "config/config.json exists"
  if command -v python3 >/dev/null 2>&1 || command -v python3.11 >/dev/null 2>&1; then
    PYCFG="$(command -v python3.11 2>/dev/null || command -v python3)"
    KEY_STATUS="$($PYCFG - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
p = Path("config/config.json")
try:
    c = json.loads(p.read_text())
except Exception as e:
    print("invalid")
    raise SystemExit
k = (c.get("gemini_api_key") or "").strip()
bad = ("", "YOUR_GEMINI_API_KEY", "ใส่ API key ของคุณที่นี่")
if not k or k in bad or "YOUR_" in k.upper() or len(k) < 20:
    print("placeholder")
else:
    print("ok")
PY
)"
    case "$KEY_STATUS" in
      ok) ok "gemini_api_key looks set" ;;
      invalid) fail "config/config.json is not valid JSON" ;;
      *) fail "gemini_api_key not set — edit config/config.json" ;;
    esac
  else
    warn "Cannot validate gemini_api_key (no python3)"
  fi
else
  fail "config/config.json missing — copy from config/config.example.json"
fi

if [[ -f pepper_main.py && -f listener_gemini_live.py ]]; then
  ok "Main entrypoints present (pepper_main.py, listener_gemini_live.py)"
else
  fail "Missing pepper_main.py or listener_gemini_live.py"
fi
echo ""

# ── Python 3 packages (inside container) ─────────────────────────────────────
if [[ "$IN_CONTAINER" -eq 1 ]]; then
  echo "== Python 3 packages =="
  PY3="$(command -v python3.11 2>/dev/null || command -v python3)"
  for pkg in faster_whisper google.generativeai pyaudio pygame numpy scipy; do
    if "$PY3" -c "import ${pkg}" >/dev/null 2>&1; then
      ok "import ${pkg}"
    else
      fail "cannot import ${pkg} — re-run post-create or: pip install -r .devcontainer/requirements.txt"
    fi
  done
  echo ""
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo "────────────────────────────────────────"
echo "  OK=$PASS  WARN=$WARN  FAIL=$FAIL"
if [[ "$FAIL" -eq 0 ]]; then
  if [[ "$IN_CONTAINER" -eq 1 ]]; then
    echo "  STATUS: READY to run"
    echo "    python2 pepper_main.py"
    echo "    python3 listener_gemini_live.py"
  else
    echo "  STATUS: READY for Dev Container"
    echo "    Open in Cursor/VS Code → Dev Containers: Reopen in Container"
    echo "    Then run: make check"
  fi
  exit 0
else
  echo "  STATUS: NOT READY"
  echo "  Fix FAIL items above, then re-run: make check"
  exit 1
fi
