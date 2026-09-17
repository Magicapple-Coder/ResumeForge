<#
ResumeForge uninstaller.

Removes what the launcher created (virtualenv, node_modules, build output and the
runtime folder). User data lives in backend\data and backend\.env and is KEPT
unless -Purge is given.

This script never deletes the source code itself: if you want the folder gone,
delete it manually after running this.

Usage:
  uninstall.cmd                 interactive
  uninstall.cmd -Purge          also delete backend\data and backend\.env
  uninstall.cmd -Yes            no questions (used by tests)
#>

[CmdletBinding()]
param(
    [switch]$Purge,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot

# Only ever operate inside a ResumeForge checkout.
if (-not (Test-Path (Join-Path $ProjectRoot "backend\app")) -or
    -not (Test-Path (Join-Path $ProjectRoot "frontend\package.json"))) {
    Write-Host "This does not look like a ResumeForge folder: $ProjectRoot" -ForegroundColor Red
    exit 1
}

$DependencyTargets = @(
    "backend\.venv",
    "frontend\node_modules",
    "frontend\dist",
    "runtime"
)
$DataTargets = @(
    "backend\data",
    "backend\.env",
    "data"
)

function Show-Plan {
    Write-Host ""
    Write-Host "ResumeForge uninstaller" -ForegroundColor Green
    Write-Host "Project: $ProjectRoot"
    Write-Host ""
    Write-Host "Will remove (created by the launcher):" -ForegroundColor Cyan
    foreach ($relative in $DependencyTargets) {
        $path = Join-Path $ProjectRoot $relative
        if (Test-Path $path) { Write-Host "  - $relative" }
    }
    if ($Purge) {
        Write-Host ""
        Write-Host "Will ALSO remove (your data, cannot be undone):" -ForegroundColor Yellow
        foreach ($relative in $DataTargets) {
            $path = Join-Path $ProjectRoot $relative
            if (Test-Path $path) { Write-Host "  - $relative" }
        }
    }
    Write-Host ""
    Write-Host "Source code and docs are kept." -ForegroundColor DarkGray
}

function Remove-Target {
    param([string]$Relative)
    $path = Join-Path $ProjectRoot $Relative
    if (-not (Test-Path $path)) { return }
    Write-Host "  removing $Relative"
    try {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Host "  could not remove $Relative : $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "  (close any running backend/frontend window and try again)" -ForegroundColor Yellow
    }
}

Show-Plan

if (-not $Yes) {
    Write-Host ""
    if ($Purge) {
        Write-Host "Type YES to delete the data listed above, or anything else to cancel: " -NoNewline
    } else {
        Write-Host "Type YES to continue (data is kept), or anything else to cancel: " -NoNewline
    }
    $answer = Read-Host
    if ($answer -ne "YES") {
        Write-Host "Cancelled. Nothing was deleted." -ForegroundColor Yellow
        exit 0
    }
}

Write-Host ""
Write-Host "Removing:" -ForegroundColor Cyan
foreach ($relative in $DependencyTargets) { Remove-Target -Relative $relative }

# Byte-code caches: safe to delete anywhere in the tree.
Get-ChildItem -LiteralPath $ProjectRoot -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike "*\.venv\*" -and $_.FullName -notlike "*\node_modules\*" } |
    ForEach-Object {
        try { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop } catch { }
    }
foreach ($relative in @("backend\.pytest_cache", "backend\.ruff_cache", ".pytest_cache")) {
    Remove-Target -Relative $relative
}

if ($Purge) {
    Write-Host ""
    Write-Host "Removing data:" -ForegroundColor Yellow
    foreach ($relative in $DataTargets) { Remove-Target -Relative $relative }
}

Write-Host ""
Write-Host "Uninstall finished." -ForegroundColor Green
if (-not $Purge) {
    Write-Host "Your data is still in backend\data (and backend\.env). To delete it too, run: uninstall.cmd -Purge"
}
Write-Host "To use ResumeForge again, run start.cmd - it will install everything from scratch."
