@echo off
rem Windows launcher: double-click in File Explorer. First run sets up a private Python environment.
cd /d "%~dp0"

set "PY="
for %%c in (py python) do (
  if not defined PY (
    %%c -c "import sys, tkinter; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=%%c"
  )
)
if not defined PY (
  echo Paper to Audio needs Python 3.10 or newer.
  echo Install it from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH".
  start "" https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

.venv\Scripts\python.exe -c "import pymupdf, edge_tts, mutagen, tkinter" >nul 2>&1
if errorlevel 1 (
  echo First run: installing components, about a minute...
  if exist .venv rmdir /s /q .venv
  %PY% -m venv .venv || goto :fail
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt || goto :fail
)

start "" .venv\Scripts\pythonw.exe paper_to_audio.py %*
exit /b 0

:fail
echo Setup failed. Check your internet connection and try again.
pause
exit /b 1
