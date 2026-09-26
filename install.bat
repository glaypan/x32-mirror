@echo off
rem ============================================================
rem  X32 Mirror - one-click installer (Windows)
rem  Double-click this file. It finds a Python with tkinter,
rem  then installs: `x32mirror` command + desktop shortcuts.
rem ============================================================
setlocal
cd /d "%~dp0"

set PY=
python -c "import tkinter" >nul 2>nul && set PY=python
if not defined PY py -3 -c "import tkinter" >nul 2>nul && set PY=py -3
if not defined PY if exist "%LocalAppData%\Programs\Python\Python313\python.exe" "%LocalAppData%\Programs\Python\Python313\python.exe" -c "import tkinter" >nul 2>nul && set PY=%LocalAppData%\Programs\Python\Python313\python.exe
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" "%LocalAppData%\Programs\Python\Python312\python.exe" -c "import tkinter" >nul 2>nul && set PY=%LocalAppData%\Programs\Python\Python312\python.exe

if not defined PY (
  echo [X] Python 3 with tkinter not found.
  echo     Please install Python 3.10+ from https://www.python.org/downloads/
  echo     ^(check "Add python.exe to PATH" during setup^), then re-run this file.
  pause
  exit /b 1
)

echo [*] Installing X32 Mirror ...
echo.
%PY% -m x32mirror install %*
echo.
pause
