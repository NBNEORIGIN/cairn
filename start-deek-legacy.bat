@echo off
REM ============================================================
REM  Deek Launcher — double-click to start API + Web UI
REM  Frontend runs as production build (npm start), not dev server
REM ============================================================
title Deek Launcher
cd /d D:\deek

echo [Deek] Stopping existing processes...
taskkill /f /fi "WINDOWTITLE eq DEEK API*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DEEK Web*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq Deek API*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq Deek Web*" >nul 2>&1

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 " 2^>nul') do (
    if not "%%a"=="0" if not "%%a"=="" (
        taskkill /f /pid %%a >nul 2>&1
    )
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " 2^>nul') do (
    if not "%%a"=="0" if not "%%a"=="" (
        taskkill /f /pid %%a >nul 2>&1
    )
)

timeout /t 3 /nobreak >nul

REM Build frontend if no production build exists
if not exist "web\.next\BUILD_ID" (
    echo [Deek] No production build found — building frontend...
    cd /d D:\deek\web
    call npm run build
    if %errorlevel% neq 0 (
        echo [Deek] Frontend build FAILED — check errors above
        pause
        exit /b 1
    )
    cd /d D:\deek
    echo [Deek] Frontend build complete.
)

echo [Deek] Starting API...
start "Deek API" cmd /k "cd /d D:\deek && .\.venv\Scripts\python -m uvicorn api.main:app --host 0.0.0.0 --port 8765"

timeout /t 5 /nobreak >nul

echo [Deek] Starting Web UI (production)...
start "Deek Web" cmd /k "cd /d D:\deek\web && npm start"

timeout /t 5 /nobreak >nul

start "" http://localhost:3000
start "" http://localhost:3000/status

echo [Deek] Started. Check the two terminal windows.
timeout /t 3 /nobreak >nul
