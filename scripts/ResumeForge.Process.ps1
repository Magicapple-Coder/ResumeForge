# ResumeForge launcher: backend/frontend startup orchestration.

function Start-ResumeForge {
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
                $systemPython = Ensure-SystemPython

                Write-Host "First run: creating Python virtual environment..."
                $venvArguments = @($systemPython.PrefixArguments) + @(
                    "-m",
                    "venv",
                    (Join-Path $BackendDirectory ".venv")
                )
                & $systemPython.Path @venvArguments
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to create the Python virtual environment."
                }
            }

            if (-not (Test-Path -LiteralPath $pythonExecutable)) {
                throw "Backend Python environment not found: $pythonExecutable"
            }

            $backendDependenciesReady = $true
            foreach ($packageName in @("fastapi", "uvicorn", "sqlalchemy", "alembic")) {
                $packagePath = Join-Path $BackendDirectory ".venv\Lib\site-packages\$packageName"
                if (-not (Test-Path -LiteralPath $packagePath -PathType Container)) {
                    $backendDependenciesReady = $false
                    break
                }
            }
            if (-not $backendDependenciesReady) {
                Write-Host "First run: installing backend dependencies..."
                & $pythonExecutable -m pip install `
                    --timeout 300 `
                    --retries 10 `
                    -r (Join-Path $BackendDirectory "requirements.txt")
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
            $nodeRuntime = Ensure-NodeRuntime
            $npmPath = $nodeRuntime.NpmPath

            $viteCommandPath = Join-Path $FrontendDirectory "node_modules\.bin\vite.cmd"
            if (-not (Test-Path -LiteralPath $viteCommandPath -PathType Leaf)) {
                Write-Host "First run: installing frontend dependencies..."
                Push-Location -LiteralPath $FrontendDirectory
                try {
                    $packageLockPath = Join-Path $FrontendDirectory "package-lock.json"
                    if (Test-Path -LiteralPath $packageLockPath) {
                        # npm ci resolves package-lock.json relative to the current
                        # directory; the launcher itself may be started elsewhere.
                        & $npmPath ci `
                            --fetch-timeout=1800000 `
                            --fetch-retries=5 `
                            --fetch-retry-mintimeout=20000 `
                            --fetch-retry-maxtimeout=120000
                    }
                    else {
                        # Older source archives may omit the lockfile. Bootstrap
                        # once with npm install instead of failing with EUSAGE.
                        Write-Warning "frontend/package-lock.json was not found; using npm install to create a local lockfile."
                        & $npmPath install `
                            --no-audit `
                            --no-fund `
                            --fetch-timeout=1800000 `
                            --fetch-retries=5 `
                            --fetch-retry-mintimeout=20000 `
                            --fetch-retry-maxtimeout=120000
                    }
                    if ($LASTEXITCODE -ne 0) {
                        throw "Failed to install frontend dependencies."
                    }
                }
                finally {
                    Pop-Location
                }
            }

            # This process-local override keeps the Vite proxy bound to the backend
            # started above without changing a user's tracked or local .env files.
            $env:VITE_BACKEND_URL = $BackendUrl
            $startedFrontend = Start-Process -FilePath $env:ComSpec `
                -ArgumentList @("/d", "/s", "/c", "`"$npmPath`" run dev -- --host 127.0.0.1 --port $FrontendPort --strictPort") `
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
}
