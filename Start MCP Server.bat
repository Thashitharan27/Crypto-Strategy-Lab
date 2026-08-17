@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

"%PYTHON%" -c "import mcp, duckdb, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Required MCP server packages are missing.
  echo Run: pip install -r requirements.txt
  pause
  exit /b 1
)

if not defined CRYPTO_STRATEGY_LAB_OUTPUT_DIR set "CRYPTO_STRATEGY_LAB_OUTPUT_DIR=%CD%\output"
if not defined CRYPTO_STRATEGY_LAB_MCP_PORT set "CRYPTO_STRATEGY_LAB_MCP_PORT=8765"
echo Starting the read-only Crypto Strategy Lab MCP server...
echo Endpoint: http://127.0.0.1:%CRYPTO_STRATEGY_LAB_MCP_PORT%/mcp
echo Output directory: %CRYPTO_STRATEGY_LAB_OUTPUT_DIR%
"%PYTHON%" -m mcp_server.server
if errorlevel 1 (
  echo.
  echo MCP server startup failed. Review the message above.
  pause
  exit /b 1
)
endlocal
