#!/usr/bin/env bash
# Runs once after the Dev Container is created.
set -euo pipefail

cd /workspaces/Pepper 2>/dev/null || cd "$(dirname "$0")/.."

echo "==> Installing Python 3 dependencies..."
python3.11 -m pip install --upgrade pip
python3.11 -m pip install -r .devcontainer/requirements.txt

# Config bootstrap (never overwrite an existing key)
if [[ ! -f config/config.json ]]; then
  echo "==> Creating config/config.json from example..."
  cp config/config.example.json config/config.json
  echo "    Edit config/config.json and set gemini_api_key."
else
  echo "==> config/config.json already exists — leaving it alone."
fi

# Whisper model (~1.6 GB) — do not auto-download (slow / can time out).
MODEL_DIR="model/thonburian-large-ct2"
MODEL_BIN="${MODEL_DIR}/model.bin"
if [[ -f "${MODEL_BIN}" ]]; then
  echo "==> Whisper model already present."
else
  echo "==> Whisper model not found. Download when ready with:"
  echo "    python3.11 -c \"from huggingface_hub import snapshot_download; snapshot_download('biodatlab/whisper-th-large-v3-combined', local_dir='${MODEL_DIR}')\""
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
