#!/usr/bin/env bash
# Runs once after the Dev Container is created.
set -euo pipefail

cd /workspaces/Pepper 2>/dev/null || cd "$(dirname "$0")/.."

echo "==> Installing Python 3 dependencies (incl. CUDA libs for Whisper)..."
python3.11 -m pip install --upgrade pip
# Prefer repo-root requirements (local venv workflow); fall back for old layouts.
if [[ -f requirements.txt ]]; then
  python3.11 -m pip install -r requirements.txt
  [[ -f requirements-cuda.txt ]] && python3.11 -m pip install -r requirements-cuda.txt || true
else
  python3.11 -m pip install -r .devcontainer/requirements.txt
fi

# Report GPU visibility (optional — falls back to CPU if none)
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "==> NVIDIA driver visible:"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
else
  echo "==> nvidia-smi not found — Whisper will use CPU (OK if this host has no GPU)."
fi
if python3.11 -c "import ctranslate2; n=ctranslate2.get_cuda_device_count(); print(f'==> ctranslate2 CUDA devices: {n}'); raise SystemExit(0 if n>0 else 0)" 2>/dev/null; then
  :
fi

# Config bootstrap (never overwrite an existing key)
if [[ ! -f config/config.json ]]; then
  echo "==> Creating config/config.json from example..."
  cp config/config.example.json config/config.json
  echo "    Edit config/config.json and set gemini_api_key."
else
  echo "==> config/config.json already exists — leaving it alone."
fi

# Whisper model (~3.1 GB) — do not auto-download (slow / can time out).
MODEL_DIR="model/thonburian-large-ct2"
MODEL_BIN="${MODEL_DIR}/model.bin"
if [[ -f "${MODEL_BIN}" ]]; then
  echo "==> Whisper model already present."
else
  echo "==> Whisper model not found. Download when ready with:"
  echo "    python3.11 -c \"from huggingface_hub import snapshot_download; snapshot_download('CodeHardThailand/whisper-th-large-v3-combined-ct2', local_dir='${MODEL_DIR}')\""
fi

# NAOqi SDK (Linux .so) — download if missing (~199 MB)
if python2 naoqi_path.py >/dev/null 2>&1; then
  echo "==> Linux NAOqi SDK found at $(python2 naoqi_path.py)"
else
  echo "==> Linux NAOqi SDK not found — downloading..."
  if bash scripts/download_pynaoqi_linux.sh; then
    echo "==> Linux NAOqi SDK ready at $(python2 naoqi_path.py)"
  else
    echo "!! WARNING: SDK download failed — pepper_main.py will not start."
    echo "   Retry with: bash scripts/download_pynaoqi_linux.sh"
    echo "   Expected: SDK_pynaoqi/linux64/lib/python2.7/site-packages/_qi.so"
  fi
fi

echo ""
echo "Dev container ready."
echo "  Listener (Python 3):  python3 listener_gemini_live.py"
echo "  Pepper   (Python 2):  python2 pepper_main.py"
echo "  HTTP tablet UI port:  8080"
