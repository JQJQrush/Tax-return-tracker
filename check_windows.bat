@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -X utf8 -m taxtracker.operations.check_setup
) else (
  where py >nul 2>nul
  if errorlevel 1 (python -X utf8 -m taxtracker.operations.check_setup) else (py -3 -X utf8 -m taxtracker.operations.check_setup)
)
pause
