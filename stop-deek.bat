@echo off
title Deek Stop
cd /d D:\deek

echo [Deek] Stopping processes...
taskkill /f /fi "WINDOWTITLE eq DEEK API*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DEEK Web*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq Deek API*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq Deek Web*" >nul 2>&1

REM Clean up any orphaned processes on our ports (skip PID 0 and empty)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 " 2^>nul') do (
    if not "%%a"=="0" if not "%%a"=="" (
        echo [Deek] Killing process on port 8765: %%a
        taskkill /f /pid %%a >nul 2>&1
    )
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " 2^>nul') do (
    if not "%%a"=="0" if not "%%a"=="" (
        echo [Deek] Killing process on port 3000: %%a
        taskkill /f /pid %%a >nul 2>&1
    )
)

echo [Deek] All processes stopped.
timeout /t 2 /nobreak >nul
