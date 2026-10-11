#!/bin/bash
# Double-click to open the Stemforge window (macOS). Uses the project's .venv.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: create the environment with Python 3.11:"
  echo "  python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[app,pitched]'"
  read -p "Press Return to close"; exit 1
fi
source .venv/bin/activate
exec python -m stemforge.app
