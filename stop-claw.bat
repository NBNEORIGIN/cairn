@echo off
title CLAW Stop
cd /d D:\claw

echo [CLAW] Stopping CLAW processes...
taskkill /f /fi "WINDOWTITLE eq CLAW API*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq CLAW Web*" >nul 2>&1

REM Clean up any orphaned processes on our ports (skip PID 0)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 "') do (
    if not "%%a"=="0" (
        echo [CLAW] Killing process on port 8765: %%a
        taskkill /f /pid %%a >nul 2>&1
    )
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 "') do (
    if not "%%a"=="0" (
        echo [CLAW] Killing process on port 3000: %%a
        taskkill /f /pid %%a >nul 2>&1
    )
)

echo [CLAW] All processes stopped.
timeout /t 2 /nobreak >nul
