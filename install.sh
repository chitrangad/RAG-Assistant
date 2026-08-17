#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# One-shot installer for bare-metal deployment (no Docker).
#
# Usage:
#   ./install.sh                              # interactive: prompts for admin password
#   ADMIN_PASSWORD=secret ./install.sh        # non-interactive admin password
#   SKIP_MODEL=1 ./install.sh                 # skip the ~1.1 GB answer-LLM download
#
# Environment overrides:
#   PYTHON          python3 binary            (default: python3)
#   VENV_DIR        virtualenv path           (default: ./.venv)
#   DATA_DIR        persistent data dir       (default: ./data)
#   ADMIN_USER      admin username            (default: admin)
#   ADMIN_PASSWORD  admin password            (default: prompted)
#   SKIP_MODEL      1 to skip model download
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
DATA_DIR="${DATA_DIR:-data}"
ADMIN_USER="${ADMIN_USER:-admin}"
PORT="${PORT:-8000}"

MODEL_URL="https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf"
MODEL_FILE="${DATA_DIR}/models/qwen3-1.7b-instruct.Q4_K_M.gguf"

log()  { printf '\033[1;32m→\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

log "Installing RAG Knowledge Assistant (bare metal)…"

# 1) Python 3.11+ check
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  err "python3 not found. Install Python 3.11+ first (https://www.python.org/downloads/)."
  exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  err "$($PYTHON --version 2>&1) is too old — Python 3.11+ is required."
  exit 1
fi

# 2) smbclient (best-effort) — lets the app reach remote UNC shares directly
#    over SMB without mounting them. Optional: mounted/local shares still work
#    without it, so a failed install is only a warning.
if ! command -v smbclient >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing smbclient (for direct UNC share access)…"
    sudo apt-get update -qq 2>/dev/null || true
    sudo apt-get install -y -qq smbclient 2>/dev/null \
      || warn "Could not install smbclient — mounted network shares still work."
  elif command -v brew >/dev/null 2>&1; then
    log "Installing samba via Homebrew (provides smbclient)…"
    brew install samba >/dev/null 2>&1 \
      || warn "Could not install smbclient — mounted network shares still work."
  else
    warn "smbclient not found — remote UNC shares need it; mounted shares still work."
  fi
else
  log "smbclient already installed."
fi

# 3) Virtualenv
if [ ! -x "$VENV_DIR/bin/python" ]; then
  log "Creating virtualenv at $VENV_DIR…"
  "$PYTHON" -m venv "$VENV_DIR"
fi
PIP="$VENV_DIR/bin/pip"
PY="$VENV_DIR/bin/python"
"$PIP" install --quiet --upgrade pip

# 3) Dependencies. CPU-only torch is installed first so sentence-transformers
#    resolves to the ~200 MB CPU build instead of the multi-GB CUDA one.
log "Installing CPU-only PyTorch…"
"$PIP" install --index-url https://download.pytorch.org/whl/cpu torch

log "Installing llama-cpp-python (prebuilt CPU wheel)…"
"$PIP" install "llama-cpp-python>=0.3.35" \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

log "Installing the application…"
"$PIP" install .

# 4) Persistent data directories
mkdir -p "$DATA_DIR/models" "$DATA_DIR/uploads" "$DATA_DIR/chroma"

# 5) Answer LLM (optional but recommended for natural-language answers)
if [ "${SKIP_MODEL:-0}" = "1" ]; then
  warn "Skipping model download (SKIP_MODEL=1). Answers will be evidence-only until a model is provided."
elif [ -f "$MODEL_FILE" ]; then
  log "Answer LLM already present — skipping download."
else
  log "Downloading the answer LLM (~1.1 GB)…"
  curl -L -C - -o "$MODEL_FILE" "$MODEL_URL"
fi

# 6) Admin credentials (created only once)
if [ ! -f "$DATA_DIR/.credentials" ]; then
  if [ -z "${ADMIN_PASSWORD:-}" ]; then
    read -rsp "Admin password (user '$ADMIN_USER'): " ADMIN_PASSWORD
    printf '\n'
  fi
  "$PY" -c "from src.auth import generate_credential_line; print(generate_credential_line('$ADMIN_USER', '$ADMIN_PASSWORD'))" \
    > "$DATA_DIR/.credentials"
  chmod 600 "$DATA_DIR/.credentials"
  log "Admin user '$ADMIN_USER' created in $DATA_DIR/.credentials"
else
  log "Admin credentials already exist — leaving untouched."
fi

log "Install complete."
printf '\nStart the server:\n'
printf '  %s -m uvicorn src.main:app --host 0.0.0.0 --port %s\n\n' "$PY" "$PORT"
printf 'Then open http://127.0.0.1:%s  (admin: http://127.0.0.1:%s/admin)\n' "$PORT" "$PORT"
printf 'See INSTALL.md §4 for a systemd service unit to keep it running.\n'
