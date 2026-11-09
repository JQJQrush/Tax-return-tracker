@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe restore_backup.py --interactive
) else (
  where py >nul 2>nul
  if errorlevel 1 (python restore_backup.py --interactive) else (py -3 restore_backup.py --interactive)
)
pause
