@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe check_setup.py
) else (
  where py >nul 2>nul
  if errorlevel 1 (python check_setup.py) else (py -3 check_setup.py)
)
pause
