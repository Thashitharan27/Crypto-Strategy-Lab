@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "print('ok')" >nul 2>nul
    if not errorlevel 1 (
        ".venv\Scripts\python.exe" combine_binance_data.py
        goto finished
    )
)

py -c "print('ok')" >nul 2>nul
if not errorlevel 1 (
    py combine_binance_data.py
    goto finished
)

python -c "print('ok')" >nul 2>nul
if not errorlevel 1 (
    python combine_binance_data.py
    goto finished
)

set "CODEX_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CODEX_PYTHON%" (
    "%CODEX_PYTHON%" combine_binance_data.py
    goto finished
)

echo.
echo The tool could not start. Install Python from https://www.python.org/downloads/
pause
exit /b 1

:finished
if errorlevel 1 pause
