@echo off
REM ============================================================
REM  CLAW Launcher — double-click to start API + Web UI
REM
REM  Auto-start removed: HKCU\...\CurrentVersion\Run\CLAW-Tray
REM  Was: "D:\claw\.venv\Scripts\python.exe" "D:\claw\tray\claw_tray.py"
REM  Removed by: start-claw.bat (see Task 6 in implementation)
REM  The tray app is no longer used — batch files manage startup.
REM ============================================================
title CLAW Launcher
cd /d D:\claw

echo [CLAW] Stopping any existing processes...
taskkill /f /fi "WINDOWTITLE eq CLAW API*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq CLAW Web*" >nul 2>&1

REM Kill any orphaned processes on our ports (skip PID 0)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 "') do (
    if not "%%a"=="0" (
        taskkill /f /pid %%a >nul 2>&1
    )
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 "') do (
    if not "%%a"=="0" (
        taskkill /f /pid %%a >nul 2>&1
    )
)

echo [CLAW] Waiting for ports to clear...
timeout /t 3 /nobreak >nul

echo [CLAW] Starting API on port 8765...
start "CLAW API" cmd /k "cd /d D:\claw && .\.venv\Scripts\python -m uvicorn api.main:app --host 0.0.0.0 --port 8765"

echo [CLAW] Waiting for API to start...
timeout /t 4 /nobreak >nul

REM Verify API started
curl -s --max-time 3 http://localhost:8765/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [CLAW] WARNING: API did not respond on port 8765 - check the CLAW API window for errors
) else (
    echo [CLAW] API is running
)

echo [CLAW] Starting Web UI on port 3000...
start "CLAW Web" cmd /k "cd /d D:\claw\web && node node_modules\next\dist\bin\next dev -p 3000"

echo [CLAW] Waiting for Web UI to start...
timeout /t 5 /nobreak >nul

echo [CLAW] Opening browser...
start "" http://localhost:3000
start "" http://localhost:3000/status

echo.
echo [CLAW] Started. Two windows are running:
echo   CLAW API  -- http://localhost:8765
echo   CLAW Web  -- http://localhost:3000
echo   Status    -- http://localhost:3000/status
echo.
echo [CLAW] This window can be closed.
timeout /t 3 /nobreak >nul
