@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" /D "%~dp0" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
    exit /b 0
)

echo The backtester's Python environment was not found.
echo Expected: %~dp0.venv\Scripts\pythonw.exe
echo.
echo Please reinstall the project requirements, then try again.
pause
exit /b 1
