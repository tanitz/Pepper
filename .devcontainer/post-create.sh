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

# NAOqi SDK check (Linux .so required; Windows .dll will not work here)
QI_LIB="SDK_pynaoqi/pynaoqi/lib"
if [[ -d "${QI_LIB}" ]]; then
  if ls "${QI_LIB}"/_qi*.so >/dev/null 2>&1 || ls "${QI_LIB}"/libqi.so* >/dev/null 2>&1; then
    echo "==> Linux NAOqi SDK looks present."
  elif ls "${QI_LIB}"/*.dll >/dev/null 2>&1; then
    echo "!! WARNING: SDK_pynaoqi looks like the Windows build (.dll)."
    echo "   For this Linux Dev Container, download the Linux pynaoqi SDK from"
    echo "   SoftBank Robotics and replace SDK_pynaoqi/ with that tree."
  else
    echo "!! WARNING: Could not find _qi.so under ${QI_LIB}."
    echo "   Place the Linux Pepper NAOqi Python 2.7 SDK under SDK_pynaoqi/."
  fi
else
  echo "!! WARNING: ${QI_LIB} missing — pepper_main.py needs the Linux pynaoqi SDK."
fi

echo ""
echo "Dev container ready."
echo "  Listener (Python 3):  python3 listener_gemini_live.py"
echo "  Pepper   (Python 2):  python2 pepper_main.py"
echo "  HTTP tablet UI port:  8080"
