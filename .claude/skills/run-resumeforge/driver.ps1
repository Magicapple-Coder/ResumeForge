# ResumeForge driver: observe and poke a RUNNING application.
#
# Lifecycle (start/stop/restart) deliberately lives in the project's own launcher,
# scripts\Start-ResumeForge.ps1 and scripts\Stop-ResumeForge.ps1. Calling that
# launcher from inside this script does not return: the processes it spawns inherit
# this script's stdout handle, so any caller waiting on the driver's output waits
# for a handle that the running app still holds. Use the launcher directly.
#
# Keep this file ASCII-only. Windows PowerShell 5.1 reads a .ps1 without a BOM as
# ANSI/GBK, so non-ASCII bytes break parsing there while PowerShell 7 reads them
# fine -- a trap that only shows up on one of the two shells.
#
# Deletions go to the recycle bin, never unlink (project rule).

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('status', 'shot', 'component', 'api')]
    [string]$Command,

    [Parameter(Position = 1)][string]$Target,
    [Parameter(Position = 2)][string]$Output,
    [string]$Method = 'GET',
    [string]$Json,
    [int]$Width = 1280,
    [int]$Height = 900,
    [int]$Budget = 12000
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$BackendUrl = 'http://127.0.0.1:8005'
$FrontendUrl = 'http://localhost:5173'
$ShotDir = Join-Path $env:TEMP 'resumeforge-shots'

function Get-Browser {
    $candidates = @(
        'C:\Program Files\Google\Chrome\Application\chrome.exe',
        'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw 'Chrome or Edge not found; cannot take screenshots.'
}

function Test-Endpoint {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-Health {
    $backend = Test-Endpoint "$BackendUrl/api/health"
    $frontend = Test-Endpoint "$FrontendUrl/"
    [pscustomobject]@{ Backend = $backend; Frontend = $frontend }
}

function Send-ToRecycleBin {
    # Project rule: never delete permanently. If the recycle bin is unavailable the
    # file is kept and reported instead of being unlinked.
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        Add-Type -AssemblyName Microsoft.VisualBasic
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
            $Path,
            [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
            [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin
        )
    } catch {
        Write-Warning "Could not move to recycle bin, file kept: $Path ($($_.Exception.Message))"
    }
}

function Invoke-Screenshot {
    param([string]$Url, [string]$Path)
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    if (Test-Path -LiteralPath $Path) { Send-ToRecycleBin -Path $Path }

    # Start-Process with an argument ARRAY, not the & call operator. When the user
    # already has a browser open, `& chrome.exe --headless --screenshot=...` is
    # handed to that running instance, which ignores the headless flags: no output,
    # no file, and $LASTEXITCODE stays empty. A dedicated --user-data-dir plus
    # Start-Process spawns a real headless instance instead.
    $profileDirectory = Join-Path $env:TEMP 'resumeforge-chrome-profile'
    # Start-Process rejects redirecting both streams to one file, so two files.
    $logPath = Join-Path $env:TEMP 'resumeforge-chrome.log'
    $outPath = Join-Path $env:TEMP 'resumeforge-chrome.out'
    $arguments = @(
        '--headless=new',
        '--disable-gpu',
        '--hide-scrollbars',
        '--no-first-run',
        "--user-data-dir=$profileDirectory",
        "--screenshot=$Path",
        "--window-size=$Width,$Height",
        "--virtual-time-budget=$Budget",
        $Url
    )
    $process = Start-Process -FilePath (Get-Browser) -ArgumentList $arguments `
        -Wait -PassThru -NoNewWindow `
        -RedirectStandardError $logPath -RedirectStandardOutput $outPath
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Screenshot failed (exit $($process.ExitCode)); browser log: $logPath"
    }
    return $Path
}

function Get-Utf8Body {
    # FastAPI returns application/json without a charset, so Windows PowerShell 5.1
    # falls back to Latin-1 and every Chinese character comes back as mojibake.
    # Re-encode the string it produced and decode those bytes as UTF-8.
    param([string]$Content)
    if (-not $Content) { return '' }
    $bytes = [System.Text.Encoding]::GetEncoding(28591).GetBytes($Content)
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    return $text.Substring(0, [Math]::Min(4000, $text.Length))
}

function Get-DefaultShotPath {
    param([string]$Name)
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    return (Join-Path $ShotDir "$stamp-$Name.png")
}

switch ($Command) {
    'status' {
        $health = Get-Health
        "backend  ($BackendUrl)  = $($health.Backend)"
        "frontend ($FrontendUrl) = $($health.Frontend)"
    }

    'shot' {
        if (-not $Target) { throw 'shot needs a path, e.g. shot /jobs' }
        if (-not (Test-Endpoint "$FrontendUrl/")) {
            throw 'Frontend is not running; run start first.'
        }
        $url = $FrontendUrl + $Target
        $path = $Output
        if (-not $path) { $path = Get-DefaultShotPath ($Target -replace '[\\/:*?"<>|]', '-').Trim('-') }
        $result = Invoke-Screenshot -Url $url -Path $path
        "screenshot: $result"
    }

    'component' {
        # Vite serves any .html in the frontend root, so a temporary page can
        # import a real component from src/ and render it without the app's API
        # dependencies. That is the only practical way to look at an isolated
        # component in a browser.
        if (-not $Target) { throw 'component needs a path, e.g. component components/settings/DataBackupCard.tsx' }
        if (-not (Test-Endpoint "$FrontendUrl/")) {
            throw 'Frontend is not running; run start first.'
        }
        $componentPath = $Target -replace '\\', '/'
        # "path#NamedExport" renders a named export; default is the module default.
        $componentExpression = 'Module.default'
        if ($componentPath -like '*#*') {
            $parts = $componentPath.Split('#', 2)
            $componentPath = $parts[0]
            $componentExpression = "Module.$($parts[1])"
        }
        $propsJson = '{}'
        if ($Json) { $propsJson = $Json }

        $probePath = Join-Path $ProjectRoot 'frontend\_probe.html'
        $probe = @"
<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>probe</title></head>
<body><div id="root" style="padding:24px"></div>
<script type="module">
import React from "react";
import { createRoot } from "react-dom/client";
import { App as AntdApp, ConfigProvider } from "antd";
import * as Module from "/src/$componentPath";
import "/src/index.css";
const Component = $componentExpression;
const props = $propsJson;
createRoot(document.getElementById("root")).render(
  React.createElement(ConfigProvider, { theme: { token: { motion: false } } },
    React.createElement(AntdApp, null, React.createElement(Component, props))),
);
</script></body></html>
"@
        Set-Content -LiteralPath $probePath -Value $probe -Encoding utf8
        try {
            Start-Sleep -Seconds 2
            $path = $Output
            if (-not $path) { $path = Get-DefaultShotPath 'component' }
            $result = Invoke-Screenshot -Url "$FrontendUrl/_probe.html" -Path $path
            "screenshot: $result"
        } finally {
            # The probe must never be left behind where it could be committed.
            Send-ToRecycleBin -Path $probePath
        }
    }

    'api' {
        if (-not $Target) { throw 'api needs a path, e.g. api /api/jobs' }
        $parameters = @{
            Uri             = ($BackendUrl + $Target)
            Method          = $Method.ToUpper()
            UseBasicParsing = $true
            TimeoutSec      = 300
        }
        if ($Json) {
            # Send UTF-8 bytes: a plain string body is encoded with the console code
            # page and corrupts non-ASCII JSON on a GBK system.
            $parameters['Body'] = [System.Text.Encoding]::UTF8.GetBytes($Json)
            $parameters['ContentType'] = 'application/json; charset=utf-8'
        }
        try {
            $response = Invoke-WebRequest @parameters
            "status: $($response.StatusCode)"
            Get-Utf8Body $response.Content
        } catch {
            $webResponse = $_.Exception.Response
            if ($null -eq $webResponse) { throw }
            $stream = $webResponse.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
            "status: $([int]$webResponse.StatusCode)"
            Get-Utf8Body $reader.ReadToEnd()
        }
    }
}
