@echo off
echo [Cairn] Starting API on port 8765...
cd /d D:\claw
start "Cairn API" cmd /k ".\.venv\Scripts\python -m uvicorn api.main:app --host 0.0.0.0 --port 8765"

echo [Cairn] Waiting for API to come up...
timeout /t 3 /nobreak >nul

echo [Cairn] Starting MCP server...
start "Cairn MCP" cmd /k ".\.venv\Scripts\python mcp\cairn_mcp_server.py"

echo [Cairn] Both services started.
echo   API:  http://localhost:8765
echo   MCP:  stdio (Claude Code)
