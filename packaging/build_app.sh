#!/bin/bash
# Build Stemforge.app with PyInstaller (macOS, run from the repo root with the project's venv active).
#   pip install -e ".[app,pitched,package]" && packaging/build_app.sh
# Output: dist/Stemforge.app   (large: it carries PySide6, numba/librosa and the Core ML model)
set -e
cd "$(dirname "$0")/.."
pyinstaller --noconfirm --clean --windowed --name Stemforge \
  --distpath "${DIST:-dist}" --workpath "${WORK:-build}" --specpath packaging \
  --paths . \
  --add-data "$(pwd)/ableton:ableton" \
  --collect-all basic_pitch --collect-all coremltools --collect-all librosa \
  --collect-all numba --collect-all llvmlite --collect-all soundfile --collect-all resampy \
  --collect-submodules stemforge \
  packaging/stemforge_app_entry.py
echo "built: ${DIST:-dist}/Stemforge.app"
