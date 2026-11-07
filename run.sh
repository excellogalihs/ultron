#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "========================================================"
echo "  ULTRON — Local-First AI Assistant for Everyday Hardware"
echo "========================================================"

PYTHON_BIN="python3"
if ! command -v python3 &>/dev/null; then
  if command -v python &>/dev/null; then
    PYTHON_BIN="python"
  else
    echo "[ERROR] Python 3 was not found. Please install Python 3.10+."
    exit 1
  fi
fi

if [ ! -d .venv ]; then
  echo "[ultron] Creating local virtual environment..."
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

if command -v ollama &>/dev/null; then
  echo "[ultron] Ollama CLI detected."
else
  echo "[NOTE] Ollama CLI not found in PATH. Ensure Ollama is running at http://localhost:11434"
fi

echo "[ultron] Starting application at http://localhost:5000"
exec .venv/bin/python app.py
