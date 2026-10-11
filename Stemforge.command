#!/bin/bash
# Double-click to open the Stemforge window (macOS). Uses the project's .venv (Python 3.11 or 3.12).
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3.11 python3.12; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
if [ ! -x .venv/bin/python ]; then
  if [ -z "$PY" ]; then
    echo "Stemforge needs Python 3.11 or 3.12 (install: brew install python@3.11)."; read -p "Press Return to close"; exit 1
  fi
  echo "First run: setting up Stemforge (a few minutes)..."
  "$PY" -m venv .venv && .venv/bin/pip install -q -e ".[app,pitched]" || { read -p "Setup failed. Press Return to close"; exit 1; }
fi
exec .venv/bin/python -m stemforge.app "$@"
