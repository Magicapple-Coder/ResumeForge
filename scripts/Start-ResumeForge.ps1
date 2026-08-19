[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$BackendPort = 8000,
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

function Test-TcpPortInUse {
    param([int]$Port)

    return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -First 1)
}

function Invoke-LocalRequest {
    param([string]$Url)

    try {
        return Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
    }
    catch {
        return $null
    }
}

function Test-ResumeForgeBackend {
    param([string]$Url)

    $response = Invoke-LocalRequest "$Url/api/health"
    if ($null -eq $response -or $response.StatusCode -ne 200) {
        return $false
    }

    try {
        return ($response.Content | ConvertFrom-Json).status -eq "ok"
    }
    catch {
        return $false
    }
}

function Test-ResumeForgeFrontend {
    param([string]$Url)

    # Check the proxied health route as well as the port. A different Vite project
    # can otherwise look healthy while sending ResumeForge requests to the wrong API.
    return Test-ResumeForgeBackend -Url $Url
}

function Wait-ForCondition {
    param(
        [scriptblock]$Condition,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    return $false
}

function Save-ProcessRecord {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$Path
    )

    @{
        process_id = $Process.Id
        started_at = $Process.StartTime.ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $Path -Encoding utf8
}

function Stop-StartedProcess {
    param([System.Diagnostics.Process]$Process)

    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}

if ($BackendPort -eq $FrontendPort) {
    throw "Backend and frontend ports must be different."
}

foreach ($directory in @($BackendDirectory, $FrontendDirectory)) {
    if (-not (Test-Path -LiteralPath $directory)) {
        throw "Project directory not found: $directory"
    }
}

New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null

$startedBackend = $null
$startedFrontend = $null

try {
    if (Test-ResumeForgeBackend -Url $BackendUrl) {
        Write-Host "Backend is already running: $BackendUrl"
    }
    elseif (Test-TcpPortInUse -Port $BackendPort) {
        throw "Port $BackendPort is in use by a non-ResumeForge backend. Close it or use -BackendPort."
    }
    else {
        $pythonExecutable = Join-Path $BackendDirectory ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $pythonExecutable)) {
            $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
            if ($null -eq $systemPython) {
                throw "Python was not found. Install Python 3.10 or later and add it to PATH."
            }

            Write-Host "First run: creating Python virtual environment..."
            & $systemPython.Source -m venv (Join-Path $BackendDirectory ".venv")
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to create the Python virtual environment."
            }
        }

        if (-not (Test-Path -LiteralPath $pythonExecutable)) {
            throw "Backend Python environment not found: $pythonExecutable"
        }

        $fastApiPackage = Join-Path $BackendDirectory ".venv\Lib\site-packages\fastapi"
        if (-not (Test-Path -LiteralPath $fastApiPackage)) {
            Write-Host "First run: installing backend dependencies..."
            & $pythonExecutable -m pip install -r (Join-Path $BackendDirectory "requirements.txt")
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to install backend dependencies."
            }
        }

        $env:PYTHONUTF8 = "1"
        $startedBackend = Start-Process -FilePath $pythonExecutable `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--log-level", "warning") `
            -WorkingDirectory $BackendDirectory `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $RuntimeDirectory "backend.stdout.log") `
            -RedirectStandardError (Join-Path $RuntimeDirectory "backend.stderr.log") `
            -PassThru
        Save-ProcessRecord -Process $startedBackend -Path $BackendPidPath

        if (-not (Wait-ForCondition -Condition { Test-ResumeForgeBackend -Url $BackendUrl })) {
            throw "Backend did not start within 30 seconds. See runtime\\backend.stderr.log."
        }
        Write-Host "Backend started: $BackendUrl"
    }

    if (Test-ResumeForgeFrontend -Url $FrontendUrl) {
        Write-Host "Frontend is already running: $FrontendUrl"
    }
    elseif (Test-TcpPortInUse -Port $FrontendPort) {
        throw "Port $FrontendPort is in use by a frontend that is not connected to this ResumeForge backend. Close it or use -FrontendPort."
    }
    else {
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($null -eq $npmCommand) {
            throw "npm was not found. Install Node.js 20.19 or later and add it to PATH."
        }

        if (-not (Test-Path -LiteralPath (Join-Path $FrontendDirectory "node_modules"))) {
            Write-Host "First run: installing frontend dependencies..."
            & $npmCommand.Source ci
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to install frontend dependencies."
            }
        }

        # This process-local override keeps the Vite proxy bound to the backend
        # started above without changing a user's tracked or local .env files.
        $env:VITE_BACKEND_URL = $BackendUrl
        $startedFrontend = Start-Process -FilePath $env:ComSpec `
            -ArgumentList @("/d", "/s", "/c", "`"$($npmCommand.Source)`" run dev -- --host 127.0.0.1 --port $FrontendPort --strictPort") `
            -WorkingDirectory $FrontendDirectory `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $RuntimeDirectory "frontend.stdout.log") `
            -RedirectStandardError (Join-Path $RuntimeDirectory "frontend.stderr.log") `
            -PassThru
        Save-ProcessRecord -Process $startedFrontend -Path $FrontendPidPath

        if (-not (Wait-ForCondition -Condition { Test-ResumeForgeFrontend -Url $FrontendUrl })) {
            throw "Frontend did not start within 30 seconds. See runtime\\frontend.stderr.log."
        }
        Write-Host "Frontend started: $FrontendUrl"
    }

    if (-not $NoBrowser) {
        Start-Process $FrontendUrl
    }

    Write-Host "`nResumeForge is ready. Double-click stop.cmd to close services."
}
catch {
    Stop-StartedProcess -Process $startedFrontend
    Stop-StartedProcess -Process $startedBackend
    if ($null -ne $startedFrontend) { Remove-Item -LiteralPath $FrontendPidPath -Force -ErrorAction SilentlyContinue }
    if ($null -ne $startedBackend) { Remove-Item -LiteralPath $BackendPidPath -Force -ErrorAction SilentlyContinue }
    throw
}
