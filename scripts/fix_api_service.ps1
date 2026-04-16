# Fix deek-api encoding issue — run as Administrator
param([string]$ClawDir = "D:\deek")

$NSSM   = Join-Path $ClawDir "scripts\nssm.exe"
$CmdExe = "$env:SystemRoot\System32\cmd.exe"
$Bat    = Join-Path $ClawDir "scripts\start_api.cmd"
$LogDir = Join-Path $ClawDir "logs\api"

Write-Host "Reinstalling deek-api with cmd.exe wrapper..." -ForegroundColor Cyan

& $NSSM stop   deek-api 2>&1 | Out-Null
& $NSSM remove deek-api confirm 2>&1 | Out-Null

& $NSSM install deek-api $CmdExe "/c `"$Bat`""
& $NSSM set deek-api AppDirectory  $ClawDir
& $NSSM set deek-api DisplayName   "DEEK API (FastAPI)"
& $NSSM set deek-api Start         SERVICE_AUTO_START
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
& $NSSM set deek-api AppStdout     (Join-Path $LogDir "stdout.log")
& $NSSM set deek-api AppStderr     (Join-Path $LogDir "stderr.log")
& $NSSM set deek-api AppRotateFiles 1
& $NSSM set deek-api AppRotateBytes 5242880
& $NSSM set deek-api AppExit       Default Restart
& $NSSM set deek-api AppRestartDelay 5000

Start-Service deek-api -ErrorAction SilentlyContinue
Start-Sleep -Seconds 6

$status = (Get-Service deek-api).Status
if ($status -eq "Running") {
    Write-Host "[OK]  deek-api: Running  ->  http://localhost:8765" -ForegroundColor Green
    Write-Host "`nLast stdout lines:" -ForegroundColor Gray
    Get-Content (Join-Path $LogDir "stdout.log") -Tail 10 -ErrorAction SilentlyContinue
} else {
    Write-Host "[ERR] deek-api: $status" -ForegroundColor Red
    Get-Content (Join-Path $LogDir "stderr.log") -Tail 15 -ErrorAction SilentlyContinue
}
