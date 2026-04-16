@echo off
title Deek Restart
cd /d D:\deek
echo [Deek] Restarting...
call stop-deek.bat
timeout /t 3 /nobreak >nul
call start-deek.bat
