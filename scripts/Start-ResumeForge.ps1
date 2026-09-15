[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$BackendPort = 8005,
    [ValidateRange(1024, 65535)]
    [int]$FrontendPort = 5173,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

# Set UTF-8 mode before any Python child process starts. pip 24.x decodes a
# BOM-less requirements file with the locale codec (cp936 on Chinese Windows),
# so without this the first-run `pip install -r requirements.txt` aborts with
# UnicodeDecodeError. venv creation, pip and the backend all inherit it.
$env:PYTHONUTF8 = "1"

# Windows PowerShell renders a progress bar per chunk on large downloads, which
# slows them down and scribbles over the launcher output.
$ProgressPreference = "SilentlyContinue"

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

# Supported interpreter window. The pins in backend\requirements.txt have no
# wheels for Python 3.14 (pydantic-core 2.33.1 publishes cp314 wheels only from
# 2.35.0), so accepting a newer interpreter means a source build that cannot
# succeed without a Rust toolchain. Keep the window here, not scattered.
# The probe is generated from these two values so the message, the discovery
# order and the venv check cannot drift apart.
$MinimumPythonVersion = [Version]"3.10"
$MaximumPythonVersion = [Version]"3.13"
$PythonVersionProbe = 'import sys; raise SystemExit(0 if ({0}, {1}) <= sys.version_info[:2] <= ({2}, {3}) else 1)' -f `
    $MinimumPythonVersion.Major, $MinimumPythonVersion.Minor, `
    $MaximumPythonVersion.Major, $MaximumPythonVersion.Minor

# Selector order for the py launcher: 3.12 first because that is the version
# this launcher installs itself and the only one the Windows CI job tests.
$PythonSupportedSelectors = @("-3.12", "-3.13", "-3.11", "-3.10")

# First run runs the migrations inside startup, and antivirus scanning a
# brand-new .venv or node_modules is slow on a cold machine.
$BackendStartTimeoutSeconds = 90
$FrontendStartTimeoutSeconds = 120

$MinimumNodeVersion = [Version]"20.19.0"
$NodeBootstrapVersion = "24.19.0"
$NodeBootstrapX64Url = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-x64.zip"
$NodeBootstrapX64Sha256 = "57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73"
$NodeBootstrapArm64Url = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-arm64.zip"
$NodeBootstrapArm64Sha256 = "8502f4a50b458d4cc38ed8f2001556c2cd239d464920f74017926ccb1e1c157f"
# Domestic mirrors of the official dist tree, tried before nodejs.org because
# that host is frequently unreachable from China. Every candidate is verified
# against the SHA-256 above, which is a constant in this repo and not fetched
# from the mirror, so a mirror cannot substitute content.
$NodeBootstrapMirrorBaseUrls = @(
    "https://mirrors.huaweicloud.com/nodejs",
    "https://cdn.npmmirror.com/binaries/node",
    "https://mirrors.cloud.tencent.com/nodejs-release"
)
$NodeDownloadAttemptTimeoutSeconds = 600
$NodeDownloadTotalBudgetSeconds = 1800
$NodeToolsDirectory = Join-Path $RuntimeDirectory "tools"

# Dot-source the focused modules so existing callers can still discover the
# same helper functions when they load this launcher script.
. (Join-Path $PSScriptRoot "ResumeForge.Common.ps1")
. (Join-Path $PSScriptRoot "ResumeForge.Python.ps1")
. (Join-Path $PSScriptRoot "ResumeForge.Node.ps1")
. (Join-Path $PSScriptRoot "ResumeForge.Process.ps1")

Start-ResumeForge
