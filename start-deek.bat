@echo off
echo [Deek] Starting API on port 8765...
cd /d D:\deek
start "Deek API" cmd /k ".\.venv\Scripts\python -m uvicorn api.main:app --host 0.0.0.0 --port 8765"

echo [Deek] Waiting for API to come up...
timeout /t 3 /nobreak >nul

echo [Deek] Starting MCP server...
start "Deek MCP" cmd /k ".\.venv\Scripts\python mcp\deek_mcp_server.py"

echo [Deek] Both services started.
echo   API:  http://localhost:8765
echo   MCP:  stdio (Claude Code)
