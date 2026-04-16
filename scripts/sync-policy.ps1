# sync-policy.ps1
# Pulls latest NBNE policy documents into a module repo's root.
#
# Usage:
#   .\scripts\sync-policy.ps1
#
# Run by:
#   - Developers locally before starting work on a module
#   - CC sessions on the Windows dev box, on demand
#
# Failure mode: if the sync fails, the existing vendored copies are restored
# from backup. The script never leaves the module in a half-synced state.

$ErrorActionPreference = "Stop"

$PolicyRepo  = "https://github.com/NBNEORIGIN/nbne-policy.git"
$TempDir     = Join-Path $env:TEMP "nbne-policy-sync-$PID"
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModuleRoot  = Split-Path -Parent $ScriptDir
$BackupDir   = Join-Path $ModuleRoot ".policy-backup-$PID"

$PolicyFiles = @(
    "NBNE_PROTOCOL.md",
    "LOCAL_CONVENTIONS.md",
    "DEEK_MODULES.md"
)

function Cleanup {
    if (Test-Path $TempDir)   { Remove-Item $TempDir   -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path $BackupDir) { Remove-Item $BackupDir -Recurse -Force -ErrorAction SilentlyContinue }
}

function RestoreBackup {
    Write-Host "ERROR: sync failed. Restoring previous policy files from backup." -ForegroundColor Red
    foreach ($file in $PolicyFiles) {
        $backupPath = Join-Path $BackupDir $file
        $modulePath = Join-Path $ModuleRoot $file
        if (Test-Path $backupPath) {
            Copy-Item $backupPath $modulePath -Force
        }
    }
    Cleanup
    exit 1
}

# Sanity check: make sure we're in a module repo
$ClaudeMd = Join-Path $ModuleRoot "CLAUDE.md"
if (-not (Test-Path $ClaudeMd)) {
    Write-Host "ERROR: $ModuleRoot does not contain CLAUDE.md." -ForegroundColor Red
    Write-Host "       This script must be run from inside a module repo." -ForegroundColor Red
    exit 1
}

Write-Host "Module: $ModuleRoot"

# Backup existing copies
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
foreach ($file in $PolicyFiles) {
    $modulePath = Join-Path $ModuleRoot $file
    if (Test-Path $modulePath) {
        Copy-Item $modulePath (Join-Path $BackupDir $file)
    }
}

# Clone fresh
Write-Host "Pulling policy from $PolicyRepo"
try {
    git clone --depth 1 --quiet $PolicyRepo $TempDir
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed with exit code $LASTEXITCODE"
    }
} catch {
    Write-Host $_ -ForegroundColor Red
    RestoreBackup
}

# Copy new versions
$missing = @()
foreach ($file in $PolicyFiles) {
    $src = Join-Path $TempDir $file
    $dst = Join-Path $ModuleRoot $file
    if (Test-Path $src) {
        Copy-Item $src $dst -Force
        Write-Host "  Updated: $file" -ForegroundColor Green
    } else {
        $missing += $file
        Write-Host "  WARNING: missing in policy source: $file" -ForegroundColor Yellow
    }
}

if ($missing.Count -gt 0) {
    Write-Host "WARNING: $($missing.Count) policy file(s) missing in source." -ForegroundColor Yellow
    Write-Host "         Existing vendored copies (if any) were preserved." -ForegroundColor Yellow
}

Cleanup

Write-Host "Sync complete." -ForegroundColor Green
