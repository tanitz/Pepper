#!/usr/bin/env bash
# Report whether Pepper is ready to run on the host (local .venv).
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

UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
VENV_PY="$ROOT/.venv/bin/python"

echo "Pepper readiness check"
echo "  workspace: $ROOT"
echo "  host:      $UNAME_S $(uname -m 2>/dev/null || true)"
echo ""

# ── Python 3 / venv ──────────────────────────────────────────────────────────
echo "== Python 3 / venv =="
if [[ -x "$VENV_PY" ]]; then
  ok "venv python: $VENV_PY ($("$VENV_PY" --version 2>&1))"
  PY3="$VENV_PY"
else
  fail "missing .venv — run: make setup"
  if command -v python3.11 >/dev/null 2>&1; then
    warn "host python3.11 available: $(command -v python3.11) (not using venv yet)"
  elif command -v python3 >/dev/null 2>&1; then
    warn "host python3 available: $(command -v python3) ($($(command -v python3) --version 2>&1))"
  fi
  PY3="$(command -v python3.11 2>/dev/null || command -v python3 || true)"
fi
echo ""

# ── Python 2 (NAOqi / pepper_main) ───────────────────────────────────────────
echo "== Python 2 (pepper_main / NAOqi) =="
if command -v python2 >/dev/null 2>&1 || command -v python2.7 >/dev/null 2>&1; then
  PY2="$(command -v python2 2>/dev/null || command -v python2.7)"
  ok "Python 2 available: $PY2 ($($PY2 --version 2>&1))"
else
  if [[ "$UNAME_S" = "Linux" ]]; then
    fail "Python 2.7 missing — needed for pepper_main.py (e.g. apt install python2.7)"
  else
    warn "Python 2.7 not on host — pepper_main.py needs Linux + python2.7 + NAOqi SDK"
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
  if [[ "$UNAME_S" = "Linux" ]]; then
    fail "NAOqi Linux SDK missing — run: make setup-sdk"
  else
    warn "NAOqi linux64 SDK missing (expected on Linux robot host) — make setup-sdk"
  fi
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
  if [[ -n "${PY3:-}" ]]; then
    KEY_STATUS="$($PY3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
p = Path("config/config.json")
try:
    c = json.loads(p.read_text())
except Exception:
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
  fail "config/config.json missing — run: make setup-config"
fi

if [[ -f pepper_main.py && -f listener_gemini_live.py ]]; then
  ok "Main entrypoints present (pepper_main.py, listener_gemini_live.py)"
else
  fail "Missing pepper_main.py or listener_gemini_live.py"
fi
echo ""

# ── Python 3 packages (venv) ─────────────────────────────────────────────────
echo "== Python 3 packages =="
if [[ -x "$VENV_PY" ]]; then
  for pkg in faster_whisper google.generativeai sounddevice pygame numpy scipy; do
    if "$VENV_PY" -c "import ${pkg}" >/dev/null 2>&1; then
      ok "import ${pkg}"
    else
      fail "cannot import ${pkg} — run: make install"
    fi
  done
  if "$VENV_PY" -c "import ctranslate2" >/dev/null 2>&1; then
    ok "import ctranslate2"
    CUDA_N="$($VENV_PY -c 'import ctranslate2; print(ctranslate2.get_cuda_device_count())' 2>/dev/null || echo 0)"
    if [[ "$CUDA_N" -gt 0 ]]; then
      ok "CUDA devices: $CUDA_N (Whisper will use GPU)"
    else
      warn "CUDA devices: 0 — Whisper will use CPU (Linux GPU: make install-cuda)"
    fi
  else
    fail "cannot import ctranslate2 — run: make install"
  fi
else
  fail "skip package imports — create venv with: make setup"
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo "────────────────────────────────────────"
echo "  OK=$PASS  WARN=$WARN  FAIL=$FAIL"
if [[ "$FAIL" -eq 0 ]]; then
  echo "  STATUS: READY to run"
  echo "    make run-listener"
  echo "    # or: source .venv/bin/activate && python listener_gemini_live.py"
  if command -v python2 >/dev/null 2>&1 || command -v python2.7 >/dev/null 2>&1; then
    echo "    python2 pepper_main.py"
  fi
  exit 0
else
  echo "  STATUS: NOT READY"
  echo "  Fix FAIL items above, then re-run: make check"
  exit 1
fi
