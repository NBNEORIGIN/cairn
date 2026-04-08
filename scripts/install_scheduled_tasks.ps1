# Cairn Windows Scheduled Task installer
# Registers tasks that run independently of the FastAPI process.
# No admin required for current-user tasks.
#
# Tasks installed:
#   Cairn-AMI-Sync  -- SP-API sync every 6 hours

param(
    [string]$ClawDir = "D:\claw"
)

$PythonExe = Join-Path $ClawDir ".venv\Scripts\python.exe"
$SyncScript = Join-Path $ClawDir "scripts\run_ami_sync.py"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python venv not found at $PythonExe"
    exit 1
}

if (-not (Test-Path $SyncScript)) {
    Write-Error "Sync script not found at $SyncScript"
    exit 1
}

Write-Host "Installing Cairn AMI sync scheduled task..."

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName "Cairn-AMI-Sync" -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName "Cairn-AMI-Sync" -Confirm:$false
    Write-Host "  Removed existing task"
}

# Action: python run_ami_sync.py
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $SyncScript `
    -WorkingDirectory $ClawDir

# Four daily triggers at 00:00, 06:00, 12:00, 18:00
$t1 = New-ScheduledTaskTrigger -Daily -At "00:00"
$t2 = New-ScheduledTaskTrigger -Daily -At "06:00"
$t3 = New-ScheduledTaskTrigger -Daily -At "12:00"
$t4 = New-ScheduledTaskTrigger -Daily -At "18:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName "Cairn-AMI-Sync" `
    -TaskPath "\Cairn\" `
    -Action $action `
    -Trigger $t1,$t2,$t3,$t4 `
    -Settings $settings `
    -Principal $principal `
    -Description "Cairn SP-API sync: orders, traffic, inventory, velocity. 4x daily." `
    | Out-Null

$registered = Get-ScheduledTask -TaskName "Cairn-AMI-Sync" -ErrorAction SilentlyContinue
if ($registered) {
    Write-Host "  [OK] Cairn-AMI-Sync registered" -ForegroundColor Green
    Write-Host "  Triggers: 00:00, 06:00, 12:00, 18:00 daily"
    Write-Host "  Script: $SyncScript"
    Write-Host ""
    Write-Host "To run a sync now (with force flag):"
    Write-Host "  $PythonExe $SyncScript --force"
    Write-Host ""
    Write-Host "Logs: $ClawDir\logs\ami_sync\ami_sync.log"
} else {
    Write-Error "Task registration failed"
    exit 1
}

Write-Host ""
Write-Host "NOTE: claw-api NSSM service requires Administrator." -ForegroundColor Yellow
Write-Host "Run install_services.ps1 as Admin to make the API survive reboots."
