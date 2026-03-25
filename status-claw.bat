@echo off
title CLAW Status
cd /d D:\claw

echo [CLAW] Checking status...
echo.

REM Check API
curl -s --max-time 2 http://localhost:8765/health >nul 2>&1
if %errorlevel% equ 0 (
    echo API         [RUNNING]  http://localhost:8765
    curl -s --max-time 2 http://localhost:8765/health
) else (
    echo API         [STOPPED]
)

echo.

REM Check Web UI
curl -s --max-time 2 http://localhost:3000 >nul 2>&1
if %errorlevel% equ 0 (
    echo Web UI      [RUNNING]  http://localhost:3000
) else (
    echo Web UI      [STOPPED]
)

echo.

REM Check ports
echo Active processes on CLAW ports:
netstat -ano | findstr ":8765 "
netstat -ano | findstr ":3000 "

echo.
pause
