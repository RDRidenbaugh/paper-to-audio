#!/bin/bash
# macOS launcher: double-click in Finder. First run sets up a private Python environment.
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  osascript -e 'display dialog "Paper to Audio needs Python 3.10 or newer (with Tkinter).\n\nInstall it from python.org/downloads, then double-click this file again." buttons {"Open python.org", "Cancel"} default button 1' \
    -e 'if button returned of result is "Open python.org" then open location "https://www.python.org/downloads/macos/"' >/dev/null 2>&1
  exit 1
fi

if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import pymupdf, edge_tts, mutagen, tkinter' 2>/dev/null; then
  echo "First run: installing components (about a minute)…"
  rm -rf .venv
  "$PY" -m venv .venv && .venv/bin/python -m pip install --quiet --upgrade pip && \
    .venv/bin/python -m pip install --quiet -r requirements.txt || { echo "Setup failed. Check your internet connection and try again."; read -r; exit 1; }
fi

.venv/bin/python paper_to_audio.py "$@" &
disown
# Close this Terminal window once the app is up.
sleep 1; osascript -e 'tell application "Terminal" to close (every window whose name contains "Start Paper to Audio")' >/dev/null 2>&1 &
