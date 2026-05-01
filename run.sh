#!/bin/bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Please install uv from https://astral.sh/uv/"
  exit 1
fi

# Ensure virtual environment exists
if [ ! -d .venv ]; then
  uv venv
fi

# Activate the environment for the current shell
if [ -n "${BASH_VERSION:-}" ]; then
  source .venv/bin/activate
else
  . .venv/bin/activate
fi

# Install Python dependencies
uv pip install playwright PyYAML

# Ensure Chromium is available for Playwright
playwright install chromium

# Check for --debug flag
if [[ "$*" == *"--debug"* ]]; then
  # Debug mode: show all output
  python main.py "$@"
else
  # Normal mode: redirect to log file, show only errors
  python main.py "$@" > usage_monitor.log 2>&1 &
  echo "Simple Usage Monitor started in background (PID: $!)"
  echo "Logs: usage_monitor.log"
  echo "To stop: kill $!"
fi
