@echo off
rem x32-mirror GUI launcher (double-click to open the desktop UI)
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python -m x32mirror gui
) else (
  py -3 -m x32mirror gui
)
if %errorlevel% neq 0 pause
