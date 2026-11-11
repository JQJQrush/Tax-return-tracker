@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
set "TRACKER_VENV=scripts\windows\.venv"
if exist .venv\Scripts\python.exe set "TRACKER_VENV=.venv"
if /I "%CD%"=="D:\Tax-return-tracker" goto canonical
if not exist "D:\Tax-return-tracker\scripts\windows\run_windows.bat" goto canonical
call "D:\Tax-return-tracker\scripts\windows\run_windows.bat"
exit /b %errorlevel%
:canonical
if exist %TRACKER_VENV%\Scripts\python.exe goto dependencies
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo 请先安装 Python 3.10 或以上版本。
    goto failed
  )
  python -m venv %TRACKER_VENV%
) else (
  py -3 -m venv %TRACKER_VENV%
)
if errorlevel 1 goto failed
:dependencies
%TRACKER_VENV%\Scripts\python.exe -c "import sys; assert sys.version_info >= (3,10)" >nul 2>nul
if errorlevel 1 (
  echo Python 版本过旧，需要 3.10 或以上版本。
  goto failed
)
%TRACKER_VENV%\Scripts\python.exe -c "import pymupdf" >nul 2>nul
if not errorlevel 1 goto launch
%TRACKER_VENV%\Scripts\python.exe -m pip install -r taxtracker\requirements.txt
if errorlevel 1 goto failed
:launch
if not defined TAXPREP_DATA_DIR set "TAXPREP_DATA_DIR=%LOCALAPPDATA%\TaxPrepLocal"
if not exist "%~dp0local-runtime.json" if not exist "local-runtime.json" goto direct
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0launch_workstation.ps1" -DataDir "%TAXPREP_DATA_DIR%"
if errorlevel 1 goto failed
exit /b 0
:direct
%TRACKER_VENV%\Scripts\python.exe -m taxtracker.runtime.server --data-dir "%TAXPREP_DATA_DIR%" --open-browser --setup-if-needed
if errorlevel 1 goto failed
exit /b 0
:failed
 echo 启动失败，请查看上方提示。可以双击 check_windows.bat 查看安装诊断。
 pause
