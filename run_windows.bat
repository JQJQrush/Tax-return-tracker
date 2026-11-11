@echo off
chcp 65001 >nul
cd /d "%~dp0"
if /I "%~dp0"=="D:\Tax-return-tracker\" goto canonical
if not exist "D:\Tax-return-tracker\run_windows.bat" goto canonical
call "D:\Tax-return-tracker\run_windows.bat"
exit /b %errorlevel%
:canonical
if exist .venv\Scripts\python.exe goto dependencies
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo 请先安装 Python 3.10 或以上版本。
    goto failed
  )
  python -m venv .venv
) else (
  py -3 -m venv .venv
)
if errorlevel 1 goto failed
:dependencies
.venv\Scripts\python.exe -c "import sys; assert sys.version_info >= (3,10)" >nul 2>nul
if errorlevel 1 (
  echo Python 版本过旧，需要 3.10 或以上版本。
  goto failed
)
.venv\Scripts\python.exe -c "import pymupdf" >nul 2>nul
if not errorlevel 1 goto launch
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
:launch
if not defined TAXPREP_DATA_DIR set "TAXPREP_DATA_DIR=%LOCALAPPDATA%\TaxPrepLocal"
if not exist "%~dp0local-runtime.json" goto direct
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0launch_workstation.ps1" -DataDir "%TAXPREP_DATA_DIR%"
if errorlevel 1 goto failed
exit /b 0
:direct
.venv\Scripts\python.exe server.py --data-dir "%TAXPREP_DATA_DIR%" --open-browser --setup-if-needed
if errorlevel 1 goto failed
exit /b 0
:failed
 echo 启动失败，请查看上方提示。可以双击 check_windows.bat 查看安装诊断。
 pause
