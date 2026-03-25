@echo off
title CLAW Restart
cd /d D:\claw
echo [CLAW] Restarting...
call stop-claw.bat
timeout /t 2 /nobreak >nul
call start-claw.bat
