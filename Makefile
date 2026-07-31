# Pepper — local Python venv setup (no Dev Container)
# Usage: make setup && make check

.PHONY: help setup setup-venv install install-cuda \
	check status ready setup-sdk setup-model setup-config \
	run-listener clean-venv doctor

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VENV := $(ROOT)/.venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
REQ  := $(ROOT)/requirements.txt
REQ_CUDA := $(ROOT)/requirements-cuda.txt

# Prefer python3.11; fall back to python3 if it is already 3.11.x
HOST_PYTHON := $(shell \
	if command -v python3.11 >/dev/null 2>&1; then command -v python3.11; \
	elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) else 1)' 2>/dev/null; then command -v python3; \
	else echo ""; fi)

UNAME_S := $(shell uname -s)

# Strip Windows CRLF so bash does not fail on `set -o pipefail` after a Windows checkout.
# Caller must pass a quoted path: $(call run_bash,"$(ROOT)/scripts/foo.sh")
define run_bash
	@sed -i.bak 's/\r$$//' $(1) && rm -f $(1).bak
	@bash $(1)
endef

help:
	@echo "Pepper Makefile (local venv)"
	@echo ""
	@echo "  make setup          Create .venv, install deps, bootstrap config"
	@echo "  make setup-venv     Create .venv with Python 3.11 only"
	@echo "  make install        pip install -r requirements.txt into .venv"
	@echo "  make install-cuda   Optional NVIDIA CUDA libs (Linux + GPU)"
	@echo "  make check          READY / NOT READY report (exit 0 when ready)"
	@echo "  make doctor         Alias for check"
	@echo "  make setup-config   Create config/config.json from example if missing"
	@echo "  make setup-sdk      Download pynaoqi linux64 into SDK_pynaoqi/linux64/"
	@echo "  make setup-model    Download Thonburian Whisper CT2 model (~3.1 GB)"
	@echo "  make run-listener   Run listener_gemini_live.py with .venv"
	@echo "  make clean-venv     Remove .venv"
	@echo ""
	@echo "Typical flow:"
	@echo "  1) make setup"
	@echo "  2) edit config/config.json  (gemini_api_key)"
	@echo "  3) make setup-model         (first time, ~3.1 GB)"
	@echo "  4) make setup-sdk           (Linux only — NAOqi for pepper_main.py)"
	@echo "  5) make check"
	@echo "  6) make run-listener"
	@echo ""
	@echo "Activate manually:  source .venv/bin/activate"

# ── Full bootstrap ───────────────────────────────────────────────────────────

setup: setup-venv install setup-config
	@echo ""
	@echo "Setup finished."
	@echo "  Optional: make setup-model"
	@if [ "$(UNAME_S)" = "Linux" ]; then \
		echo "  Optional: make setup-sdk   (NAOqi for pepper_main.py)"; \
		echo "  Optional: make install-cuda  (NVIDIA GPU Whisper)"; \
	else \
		echo "  Note: NAOqi linux64 SDK / CUDA are Linux-oriented;"; \
		echo "        listener (Python 3) works on this host via .venv."; \
	fi
	@echo "  Then: make check && make run-listener"
	@echo "  Or:   source .venv/bin/activate && python listener_gemini_live.py"

# ── Virtualenv ───────────────────────────────────────────────────────────────

setup-venv:
	@if [ -z "$(HOST_PYTHON)" ]; then \
		echo "[FAIL] Python 3.11 not found."; \
		echo "       macOS:  brew install python@3.11"; \
		echo "       Ubuntu: sudo apt install python3.11 python3.11-venv python3.11-dev"; \
		exit 1; \
	fi
	@if [ ! -x "$(PY)" ]; then \
		ver=$$("$(HOST_PYTHON)" --version 2>&1); \
		echo "==> Creating venv at $(VENV) with $$ver"; \
		"$(HOST_PYTHON)" -m venv "$(VENV)"; \
	else \
		echo "[OK] venv already exists: $(VENV)"; \
	fi
	@ver=$$("$(PY)" --version 2>&1); echo "[OK] interpreter: $$ver"

install: setup-venv
	@echo "==> Upgrading pip..."
	@"$(PY)" -m pip install --upgrade pip
	@echo "==> Installing requirements from $(REQ)..."
	@"$(PIP)" install -r "$(REQ)"
	@echo "[OK] Python 3 packages installed into .venv"
	@if [ "$(UNAME_S)" = "Darwin" ]; then \
		echo ""; \
		echo "Tip (macOS audio): if pyaudio fails to import, run:"; \
		echo "  brew install portaudio && make install"; \
	fi

install-cuda: setup-venv
	@if [ "$(UNAME_S)" != "Linux" ]; then \
		echo "[FAIL] install-cuda is for Linux + NVIDIA only (this host: $(UNAME_S))"; \
		exit 1; \
	fi
	@if ! command -v nvidia-smi >/dev/null 2>&1; then \
		echo "[WARN] nvidia-smi not found — installing CUDA wheels anyway"; \
	fi
	@echo "==> Installing CUDA libs from $(REQ_CUDA)..."
	@"$(PIP)" install -r "$(REQ_CUDA)"
	@echo "[OK] CUDA packages installed"

# ── Assets ───────────────────────────────────────────────────────────────────

setup-config:
	@mkdir -p "$(ROOT)/config"
	@if [ -f "$(ROOT)/config/config.json" ]; then \
		echo "[OK] config/config.json already exists"; \
	else \
		cp "$(ROOT)/config/config.example.json" "$(ROOT)/config/config.json"; \
		echo "[OK] created config/config.json — set gemini_api_key"; \
	fi

setup-sdk:
	$(call run_bash,"$(ROOT)/scripts/download_pynaoqi_linux.sh")

setup-model: setup-venv
	@echo "==> Downloading Thonburian Whisper CT2 (~3.1 GB)..."
	@if [ ! -f "$(ROOT)/model/thonburian-large-ct2/model.bin" ] \
		&& [ -f "$(ROOT)/model/thonburian-large-ct2/model.safetensors" ]; then \
		echo "==> Removing incompatible Transformers checkpoint..."; \
		rm -f "$(ROOT)/model/thonburian-large-ct2/model.safetensors"; \
	fi
	@"$(PY)" -c "from huggingface_hub import snapshot_download; snapshot_download('CodeHardThailand/whisper-th-large-v3-combined-ct2', local_dir='$(ROOT)/model/thonburian-large-ct2')"
	@test -f "$(ROOT)/model/thonburian-large-ct2/model.bin" \
		&& echo "[OK] model.bin ready" \
		|| (echo "[FAIL] model.bin still missing"; exit 1)

# ── Run / check ──────────────────────────────────────────────────────────────

check status ready doctor:
	$(call run_bash,"$(ROOT)/scripts/check_ready.sh")

run-listener: setup-venv
	@test -x "$(PY)" || (echo "[FAIL] missing .venv — run: make setup"; exit 1)
	@"$(PY)" "$(ROOT)/listener_gemini_live.py"

clean-venv:
	@rm -rf "$(VENV)"
	@echo "[OK] removed $(VENV)"
