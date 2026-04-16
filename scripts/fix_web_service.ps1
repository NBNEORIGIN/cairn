# Quick fix for deek-web service — run as Administrator
param([string]$ClawDir = "D:\deek")

$NSSM      = Join-Path $ClawDir "scripts\nssm.exe"
$CmdExe    = "$env:SystemRoot\System32\cmd.exe"
$StartWeb  = Join-Path $ClawDir "scripts\start_web.cmd"
$WebDir    = Join-Path $ClawDir "web"
$LogDir    = Join-Path $ClawDir "logs\web"

Write-Host "Cmd    : $CmdExe"
Write-Host "Script : $StartWeb"

# Remove old service
& $NSSM stop   deek-web 2>&1 | Out-Null
& $NSSM remove deek-web confirm 2>&1 | Out-Null

# Recreate using cmd.exe /c start_web.cmd — auto-builds before starting
& $NSSM install deek-web $CmdExe "/c `"$StartWeb`""
& $NSSM set deek-web AppDirectory     $WebDir
& $NSSM set deek-web DisplayName      "DEEK Web Chat (Next.js)"
& $NSSM set deek-web Start            SERVICE_AUTO_START
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
& $NSSM set deek-web AppStdout  (Join-Path $LogDir "stdout.log")
& $NSSM set deek-web AppStderr  (Join-Path $LogDir "stderr.log")
& $NSSM set deek-web AppRotateFiles 1
& $NSSM set deek-web AppRotateBytes 5242880
& $NSSM set deek-web AppExit    Default Restart
& $NSSM set deek-web AppRestartDelay 5000

# Start it
Start-Service deek-web -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

$status = (Get-Service deek-web).Status
if ($status -eq "Running") {
    Write-Host "[OK]  deek-web: Running  ->  http://localhost:3000" -ForegroundColor Green
} else {
    Write-Host "[ERR] deek-web: $status" -ForegroundColor Red
    Write-Host "stderr:" -ForegroundColor Yellow
    Get-Content (Join-Path $LogDir "stderr.log") -Tail 15 -ErrorAction SilentlyContinue
    Write-Host "stdout:" -ForegroundColor Yellow
    Get-Content (Join-Path $LogDir "stdout.log") -Tail 15 -ErrorAction SilentlyContinue
}
