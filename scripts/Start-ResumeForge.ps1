[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$BackendPort = 8005,
    [ValidateRange(1024, 65535)]
    [int]$FrontendPort = 5173,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendDirectory = Join-Path $ProjectRoot "backend"
$FrontendDirectory = Join-Path $ProjectRoot "frontend"
$RuntimeDirectory = Join-Path $ProjectRoot "runtime"
$BackendUrl = "http://127.0.0.1:$BackendPort"
$FrontendUrl = "http://127.0.0.1:$FrontendPort"
$BackendPidPath = Join-Path $RuntimeDirectory "backend.json"
$FrontendPidPath = Join-Path $RuntimeDirectory "frontend.json"
$PythonBootstrapVersion = "3.12.10"
$PythonBootstrapUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
$PythonBootstrapSha256 = "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
$MinimumNodeVersion = [Version]"20.19.0"
$NodeBootstrapVersion = "24.19.0"
$NodeBootstrapX64Url = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-x64.zip"
$NodeBootstrapX64Sha256 = "57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73"
$NodeBootstrapArm64Url = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-arm64.zip"
$NodeBootstrapArm64Sha256 = "8502f4a50b458d4cc38ed8f2001556c2cd239d464920f74017926ccb1e1c157f"
$NodeToolsDirectory = Join-Path $RuntimeDirectory "tools"

# Dot-source the focused modules so existing callers can still discover the
# same helper functions when they load this launcher script.
. (Join-Path $PSScriptRoot "ResumeForge.Common.ps1")
. (Join-Path $PSScriptRoot "ResumeForge.Python.ps1")
. (Join-Path $PSScriptRoot "ResumeForge.Node.ps1")
. (Join-Path $PSScriptRoot "ResumeForge.Process.ps1")

Start-ResumeForge
