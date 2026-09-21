<#
ResumeForge updater.

Updates the program files only. User data lives in data\ (database, datasets,
backups) and in .env, so those paths are never overwritten.

Two modes:
  * git checkout  -> git pull --ff-only, then sync dependencies
  * plain folder  -> download the repository zip and copy program files over

Run it from the project root with:  update.cmd
#>

[CmdletBinding()]
param(
    [switch]$SkipDependencies,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot
$Repository = if ($env:RESUMEFORGE_UPDATE_REPO) { $env:RESUMEFORGE_UPDATE_REPO } else { "Magicapple-Coder/ResumeForge" }
$ArchiveUrl = "https://github.com/$Repository/archive/refs/heads/main.zip"

# Paths that belong to the user or to the local environment; never overwritten.
$ExcludedNames = @(
    "data",
    "runtime",
    ".git",
    ".env",
    "node_modules",
    ".venv",
    "dist",
    "__pycache__",
    ".pytest_cache",
    "coverage"
)

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $ProjectRoot
    )
    Write-Host ("    " + $FilePath + " " + ($Arguments -join " "))
    if ($DryRun) { return }
    # Native commands write progress to stderr; with $ErrorActionPreference = Stop
    # that would abort the script, so roll it back for the duration of the call.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        Push-Location $WorkingDirectory
        & $FilePath @Arguments
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        throw "$FilePath exited with code $code"
    }
}

function Test-Excluded {
    param([string]$Name)
    return $ExcludedNames -contains $Name
}

function Copy-ProgramFiles {
    param(
        [string]$Source,
        [string]$Destination
    )
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        if (Test-Excluded -Name $_.Name) { return }
        $target = Join-Path $Destination $_.Name
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Force -Path $target | Out-Null
            Copy-ProgramFiles -Source $_.FullName -Destination $target
        } else {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}

Write-Host "ResumeForge updater" -ForegroundColor Green
Write-Host "Project: $ProjectRoot"
if ($DryRun) {
    Write-Host "Dry run: no file will be changed." -ForegroundColor Yellow
}

Write-Step "Checking repository"
$gitDirectory = Join-Path $ProjectRoot ".git"
$useGit = (Test-Path $gitDirectory) -and (Get-Command git -ErrorAction SilentlyContinue)

if ($useGit) {
    Write-Step "Pulling the latest code (git pull --ff-only)"
    Invoke-External -FilePath "git" -Arguments @("-C", $ProjectRoot, "pull", "--ff-only")
} elseif ($DryRun) {
    # 预览时既没下载也没解压，$staging 根本不存在；这里必须整个跳过，
    # 否则下面的 Get-ChildItem 会撞上"路径不存在"并把脚本终止掉
    # （$ErrorActionPreference = Stop 下它是终止性错误）。
    Write-Host "Would download $ArchiveUrl and copy program files over $ProjectRoot." -ForegroundColor Yellow
    Write-Host "    data, .env, runtime, .venv and node_modules would be kept." -ForegroundColor DarkGray
} else {
    Write-Step "Downloading the latest archive"
    $staging = Join-Path $ProjectRoot ("runtime\update-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    $archive = Join-Path $staging "resumeforge.zip"
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $archive -UseBasicParsing
    Expand-Archive -LiteralPath $archive -DestinationPath $staging -Force
    $extracted = Get-ChildItem -LiteralPath $staging -Directory | Select-Object -First 1
    if (-not $extracted) {
        throw "The downloaded archive did not contain a folder. Download it manually from https://github.com/$Repository/releases"
    }
    Write-Step "Copying program files (data, .env and runtime are kept)"
    Copy-ProgramFiles -Source $extracted.FullName -Destination $ProjectRoot
    Write-Host "    Source kept at: $staging" -ForegroundColor DarkGray
}

if ($SkipDependencies) {
    Write-Step "Dependency sync skipped (-SkipDependencies)"
} else {
    $requirements = Join-Path $ProjectRoot "backend\requirements.txt"
    $venvPython = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
    if ((Test-Path $requirements) -and (Test-Path $venvPython)) {
        Write-Step "Syncing backend dependencies"
        Invoke-External -FilePath $venvPython -Arguments @(
            "-m", "pip", "install", "--disable-pip-version-check", "-r", $requirements
        ) -WorkingDirectory (Join-Path $ProjectRoot "backend")
    } else {
        Write-Host "    Backend virtual environment not found; it will be created on the next start."
    }

    $packageJson = Join-Path $ProjectRoot "frontend\package.json"
    $nodeModules = Join-Path $ProjectRoot "frontend\node_modules"
    if ((Test-Path $packageJson) -and (Test-Path $nodeModules) -and (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Step "Syncing frontend dependencies (npm ci)"
        Invoke-External -FilePath "npm" -Arguments @("ci", "--no-audit", "--no-fund") -WorkingDirectory (Join-Path $ProjectRoot "frontend")
    } else {
        Write-Host "    Frontend dependencies not installed; they will be installed on the next start."
    }
}

Write-Host ""
if ($DryRun) {
    Write-Host "Dry run finished: nothing was downloaded, copied or installed." -ForegroundColor Yellow
} else {
    Write-Host "Update finished." -ForegroundColor Green
    Write-Host "Start the app again with start.cmd. Your data in data\ was not touched." -ForegroundColor Green
}
