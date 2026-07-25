# Pepper — readiness helpers for Docker / Dev Container
# Usage: make check

.PHONY: help check status ready docker-check setup setup-sdk setup-model setup-config

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# Strip Windows CRLF so bash does not fail on `set -o pipefail` after a Windows checkout.
define run_bash
	@sed -i 's/\r$$//' $(1)
	@bash $(1)
endef

help:
	@echo "Pepper Makefile"
	@echo ""
	@echo "  make check         Check if Docker/Dev Container + assets are ready to run"
	@echo "  make status        Alias for check"
	@echo "  make ready         Alias for check (exit 0 only when READY)"
	@echo "  make docker-check  Check Docker daemon + Dev Container files only"
	@echo "  make setup         Bootstrap config + download Linux NAOqi SDK"
	@echo "  make setup-sdk     Download pynaoqi linux64 into SDK_pynaoqi/linux64/"
	@echo "  make setup-model   Download Thonburian Whisper CT2 model (~1.6 GB)"
	@echo "  make setup-config  Create config/config.json from example if missing"
	@echo ""
	@echo "Typical flow:"
	@echo "  1) make docker-check"
	@echo "  2) Dev Containers: Reopen in Container"
	@echo "  3) make check"
	@echo "  4) fix FAIL items / make setup*"

check status ready:
	$(call run_bash,"$(ROOT)/scripts/check_ready.sh")

docker-check:
	@echo "== Docker daemon =="
	@command -v docker >/dev/null 2>&1 \
		&& echo "  [OK]   docker CLI: $$(command -v docker)" \
		|| (echo "  [FAIL] docker CLI not found — install Docker Desktop / OrbStack"; exit 1)
	@if docker info >/dev/null 2>&1; then \
		echo "  [OK]   Docker daemon is running"; \
	else \
		err=$$(docker info 2>&1 | tail -n 1 | tr -d '\r'); \
		echo "  [FAIL] Docker daemon not ready — start OrbStack / Docker Desktop"; \
		echo "         $$err"; \
		exit 1; \
	fi
	@echo ""
	@echo "== Dev Container files =="
	@test -f "$(ROOT)/.devcontainer/devcontainer.json" \
		&& echo "  [OK]   .devcontainer/devcontainer.json" \
		|| (echo "  [FAIL] missing .devcontainer/devcontainer.json"; exit 1)
	@test -f "$(ROOT)/.devcontainer/Dockerfile" \
		&& echo "  [OK]   .devcontainer/Dockerfile" \
		|| (echo "  [FAIL] missing .devcontainer/Dockerfile"; exit 1)
	@test -f "$(ROOT)/.devcontainer/post-create.sh" \
		&& echo "  [OK]   .devcontainer/post-create.sh" \
		|| (echo "  [FAIL] missing .devcontainer/post-create.sh"; exit 1)
	@echo ""
	@echo "  STATUS: Docker is ready for Dev Container"
	@echo "  Next: Cursor/VS Code → Dev Containers: Reopen in Container"
	@echo "  Then: make check"

setup: setup-config setup-sdk
	@echo ""
	@echo "Setup finished. Optional: make setup-model"
	@echo "Then: make check"

setup-sdk:
	$(call run_bash,"$(ROOT)/scripts/download_pynaoqi_linux.sh")

setup-model:
	@echo "==> Downloading Thonburian Whisper CT2 (~1.6 GB)..."
	@PY=$$(command -v python3.11 2>/dev/null || command -v python3); \
	if [ -z "$$PY" ]; then echo "[FAIL] python3 not found"; exit 1; fi; \
	$$PY -c "from huggingface_hub import snapshot_download; snapshot_download('biodatlab/whisper-th-large-v3-combined', local_dir='$(ROOT)/model/thonburian-large-ct2')"
	@test -f "$(ROOT)/model/thonburian-large-ct2/model.bin" \
		&& echo "[OK] model.bin ready" \
		|| (echo "[FAIL] model.bin still missing"; exit 1)

setup-config:
	@mkdir -p "$(ROOT)/config"
	@if [ -f "$(ROOT)/config/config.json" ]; then \
		echo "[OK] config/config.json already exists"; \
	else \
		cp "$(ROOT)/config/config.example.json" "$(ROOT)/config/config.json"; \
		echo "[OK] created config/config.json — set gemini_api_key"; \
	fi
