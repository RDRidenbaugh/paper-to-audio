@echo off
rem Windows launcher: double-click in File Explorer. First run sets up a private Python environment.
rem
rem This never changes into the app folder, so it also works when the folder is on a network
rem share or inside WSL (\\wsl.localhost\...), which CMD can't use as a current directory.
rem The Python environment lives in %LOCALAPPDATA% rather than next to this file for the same reason.
setlocal
set "APP=%~dp0"
set "VENV=%LOCALAPPDATA%\PaperToAudio\venv"

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

"%VENV%\Scripts\python.exe" -c "import pymupdf, edge_tts, mutagen, tkinter" >nul 2>&1
if errorlevel 1 (
  echo First run: installing components into %VENV%
  echo This takes about a minute...
  if exist "%VENV%" rmdir /s /q "%VENV%"
  %PY% -m venv "%VENV%"
  if errorlevel 1 (
    echo.
    echo Could not create the Python environment in %VENV%
    goto :fail
  )
  "%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
  "%VENV%\Scripts\python.exe" -m pip install --quiet -r "%APP%requirements.txt"
  if errorlevel 1 (
    echo.
    echo Installing components failed. Check your internet connection and try again.
    goto :fail
  )
)

start "" "%VENV%\Scripts\pythonw.exe" "%APP%paper_to_audio.py" %*
exit /b 0

:fail
pause
exit /b 1
