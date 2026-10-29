@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m crypto_strategy_lab.photon_live
) else (
  python -m crypto_strategy_lab.photon_live
)
pause
