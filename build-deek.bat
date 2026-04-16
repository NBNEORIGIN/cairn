@echo off
echo [Deek] Building frontend...
cd /d D:\deek\web
call npm run build
if %errorlevel% equ 0 (
    echo [Deek] Build complete.
) else (
    echo [Deek] Build FAILED — check errors above
    pause
    exit /b 1
)

echo.
echo [Deek] Starting Deek API on port 8765...
cd /d D:\deek
start "Deek API" cmd /k ".\.venv\Scripts\python -m uvicorn api.main:app --host 0.0.0.0 --port 8765"

REM Start Deek MCP Server (if built)
if exist "D:\deek\mcp\deek_mcp_server.py" (
    echo [Deek] Starting MCP server...
    start "Deek MCP" cmd /k ".\.venv\Scripts\python mcp\deek_mcp_server.py"
) else (
    echo [Deek] MCP server not found — skipping
)

echo.
echo [Deek] Ready. API running on http://localhost:8765
echo [Deek] Use: cairn "your prompt" project_name
pause
