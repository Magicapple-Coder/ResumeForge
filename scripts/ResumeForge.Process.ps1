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

    # Named once and reused by the redirects and by the failure messages, so the
    # path a user is told to look at is always the file the process writes.
    $backendStandardOutputPath = Join-Path $RuntimeDirectory "backend.stdout.log"
    $backendLogPath = Join-Path $RuntimeDirectory "backend.stderr.log"
    $frontendStandardOutputPath = Join-Path $RuntimeDirectory "frontend.stdout.log"
    $frontendLogPath = Join-Path $RuntimeDirectory "frontend.stderr.log"

    $startedBackend = $null
    $startedFrontend = $null

    try {
        $backendRecordPattern = Get-ResumeForgeProcessPattern -Service "backend"
        $backendRunning = Test-ResumeForgeBackend -Url $BackendUrl
        if (-not $backendRunning -and (Test-TcpPortInUse -Port $BackendPort)) {
            # A leftover backend of ours can hold the port while failing the health
            # check (it crashed, or the process was replaced mid-flight). Stop that
            # one and start clean instead of telling the user to hunt it down.
            if ($null -eq (Get-ProcessRecordMatch -RecordPath $BackendPidPath -CommandPattern $backendRecordPattern)) {
                throw "Port $BackendPort is in use by a non-ResumeForge backend. Close it or use -BackendPort."
            }
            Write-Warning "A previous ResumeForge backend still holds port $BackendPort; stopping it and starting a fresh one."
            Stop-RecordedProcess -DisplayName "backend" -RecordPath $BackendPidPath -CommandPattern $backendRecordPattern
            Start-Sleep -Milliseconds 800
        }

        if ($backendRunning) {
            Write-Host "Backend is already running: $BackendUrl"
        }
        else {
            $pythonExecutable = Join-Path $BackendDirectory ".venv\Scripts\python.exe"
            $venvConfigPath = Join-Path $BackendDirectory ".venv\pyvenv.cfg"
            if ((Test-Path -LiteralPath $pythonExecutable) -and
                -not (Test-VenvVersionSupported -ConfigPath $venvConfigPath)) {
                # A venv built by an out-of-window interpreter can never install
                # the pinned wheels, so reusing it makes every run fail the same
                # way. Move it aside rather than delete: the project keeps
                # derived artifacts recoverable, and a rename is free on the
                # same volume. runtime/ is git-ignored.
                $staleVenvPath = Join-Path $RuntimeDirectory ("venv-unsupported-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
                Write-Warning "backend\.venv was created by an unsupported Python version. Moving it to $staleVenvPath and recreating it."
                Move-Item -LiteralPath (Join-Path $BackendDirectory ".venv") -Destination $staleVenvPath
            }
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

            # Ask the interpreter to import the packages instead of looking for
            # four directory names: a venv that lost pydantic, or whose wheels
            # were built for another interpreter, otherwise passes the check and
            # then dies at import time with only "did not start" to show for it.
            #
            # This probe is expected to fail on a fresh venv, and Python writes
            # the ImportError traceback to stderr. With ErrorActionPreference
            # set to Stop, PowerShell raises a terminating NativeCommandError for
            # any stderr output from a native command, so the preference has to
            # be relaxed for the duration: the exit code is the signal here.
            $probePreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                & $pythonExecutable -c "import fastapi, uvicorn, sqlalchemy, alembic, pydantic, pydantic_settings, PIL, pypdf, fpdf" 2>&1 | Out-Null
                $dependencyProbeExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $probePreference
            }
            if ($dependencyProbeExitCode -ne 0) {
                Write-Host "First run: installing backend dependencies..."
                & $pythonExecutable -m pip install `
                    --timeout 300 `
                    --retries 10 `
                    -r (Join-Path $BackendDirectory "requirements.txt")
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to install backend dependencies."
                }
            }

            # PYTHONUTF8 is set once at the top of Start-ResumeForge.ps1 so that
            # venv creation, pip and the backend all inherit it.
            $startedBackend = Start-Process -FilePath $pythonExecutable `
                -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--log-level", "warning") `
                -WorkingDirectory $BackendDirectory `
                -WindowStyle Hidden `
                -RedirectStandardOutput $backendStandardOutputPath `
                -RedirectStandardError $backendLogPath `
                -PassThru
            Save-ProcessRecord -Process $startedBackend -Path $BackendPidPath

            if (-not (Wait-ForCondition -Condition { Test-ResumeForgeBackend -Url $BackendUrl } `
                    -TimeoutSeconds $BackendStartTimeoutSeconds -FailFastProcess $startedBackend)) {
                if ($startedBackend.HasExited) {
                    throw (Format-ServiceStartFailure -DisplayName "Backend" `
                            -Reason "exited with code $(Get-ProcessExitCodeText -Process $startedBackend) before becoming healthy" `
                            -LogPath $backendLogPath)
                }
                throw (Format-ServiceStartFailure -DisplayName "Backend" `
                        -Reason "did not start within $BackendStartTimeoutSeconds seconds" `
                        -LogPath $backendLogPath)
            }
            Write-Host "Backend started: $BackendUrl"
        }

        $frontendRecordPattern = Get-ResumeForgeProcessPattern -Service "frontend"
        $frontendRunning = Test-ResumeForgeFrontend -Url $FrontendUrl
        if (-not $frontendRunning -and (Test-TcpPortInUse -Port $FrontendPort)) {
            # Same as the backend above: our own leftover Vite process fails the
            # proxied health check once its backend is gone, and it is ours to stop.
            if ($null -eq (Get-ProcessRecordMatch -RecordPath $FrontendPidPath -CommandPattern $frontendRecordPattern)) {
                throw "Port $FrontendPort is in use by a frontend that is not connected to this ResumeForge backend. Close it or use -FrontendPort."
            }
            Write-Warning "A previous ResumeForge frontend still holds port $FrontendPort; stopping it and starting a fresh one."
            Stop-RecordedProcess -DisplayName "frontend" -RecordPath $FrontendPidPath -CommandPattern $frontendRecordPattern
            Start-Sleep -Milliseconds 800
        }

        if ($frontendRunning) {
            Write-Host "Frontend is already running: $FrontendUrl"
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
            # Hand npm.cmd to Start-Process as the program. PowerShell wraps a
            # .cmd in cmd.exe itself and, unlike a hand-written
            # "cmd /c ""<path>" args" line, does the quoting correctly: a path
            # containing spaces used to arrive unquoted and cmd tried to run
            # "C:\Program". The recorded process is still cmd.exe, so stop.cmd
            # keeps recognising it.
            $startedFrontend = Start-Process -FilePath $npmPath `
                -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort", "--strictPort") `
                -WorkingDirectory $FrontendDirectory `
                -WindowStyle Hidden `
                -RedirectStandardOutput $frontendStandardOutputPath `
                -RedirectStandardError $frontendLogPath `
                -PassThru
            Save-ProcessRecord -Process $startedFrontend -Path $FrontendPidPath

            if (-not (Wait-ForCondition -Condition { Test-ResumeForgeFrontend -Url $FrontendUrl } `
                    -TimeoutSeconds $FrontendStartTimeoutSeconds -FailFastProcess $startedFrontend)) {
                if ($startedFrontend.HasExited) {
                    throw (Format-ServiceStartFailure -DisplayName "Frontend" `
                            -Reason "exited with code $(Get-ProcessExitCodeText -Process $startedFrontend) before becoming healthy" `
                            -LogPath $frontendLogPath)
                }
                throw (Format-ServiceStartFailure -DisplayName "Frontend" `
                        -Reason "did not start within $FrontendStartTimeoutSeconds seconds" `
                        -LogPath $frontendLogPath)
            }
            Write-Host "Frontend started: $FrontendUrl"
        }

        if (-not $NoBrowser) {
            # A machine without a default-browser association makes this throw,
            # and the catch below would then tear down the services we just
            # started. Failing to open a window is not a reason to stop the app.
            try {
                Start-Process $FrontendUrl
            }
            catch {
                Write-Warning "Could not open a browser automatically. Open $FrontendUrl manually."
            }
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
