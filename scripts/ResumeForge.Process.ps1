# ResumeForge launcher: backend/frontend startup orchestration.

function Start-ResumeForge {
    if ($BackendPort -eq $FrontendPort) {
        throw "后端端口与前端端口不能相同：两者都是 $BackendPort。请用 -BackendPort / -FrontendPort 指定不同的端口。"
    }

    foreach ($directory in @($BackendDirectory, $FrontendDirectory)) {
        if (-not (Test-Path -LiteralPath $directory)) {
            throw "找不到项目目录：$directory。请确认解压出来的文件夹没有被移动或删除。"
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
                throw ("端口 $BackendPort 已被别的程序占用（不是简历通自己的后端，所以不会去动它）。`n" +
                "怎么办（二选一）：`n" +
                "  1) 关掉占用该端口的程序；`n" +
                "  2) 换一个端口启动：start.cmd -BackendPort 8010")
            }
            Write-Warning "上一次运行留下的简历通后端正占着端口 $BackendPort，先停掉它再启动一个新的。"
            Stop-RecordedProcess -DisplayName "backend" -RecordPath $BackendPidPath -CommandPattern $backendRecordPattern
            Start-Sleep -Milliseconds 800
        }

        if ($backendRunning) {
            Write-Host "后端已经在运行：$BackendUrl"
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
                Write-Warning "backend\.venv 是用不受支持的 Python 版本建的，已移到 $staleVenvPath 并重建（原目录没有被删除，需要时可手动找回）。"
                Move-Item -LiteralPath (Join-Path $BackendDirectory ".venv") -Destination $staleVenvPath
            }
            if (-not (Test-Path -LiteralPath $pythonExecutable)) {
                $systemPython = Ensure-SystemPython

                Write-Host "首次运行：正在创建 Python 虚拟环境（这一步只做一次）..."
                $venvArguments = @($systemPython.PrefixArguments) + @(
                    "-m",
                    "venv",
                    (Join-Path $BackendDirectory ".venv")
                )
                & $systemPython.Path @venvArguments
                if ($LASTEXITCODE -ne 0) {
                    throw ("创建 Python 虚拟环境失败。`n" +
                    "怎么办：`n" +
                    "  1) 确认 backend 目录可写（没有被设为只读、也没有被安全软件锁定）；`n" +
                    "  2) 删掉 backend\.venv 后重新双击 start.cmd；`n" +
                    "  3) 仍失败：手动执行 backend\.venv\Scripts\python.exe 所在目录的创建命令，或到 GitHub Issues 反馈并附上上面的报错。")
                }
            }

            if (-not (Test-Path -LiteralPath $pythonExecutable)) {
                throw ("没有找到后端的 Python 环境：$pythonExecutable`n" +
                    "怎么办：删掉 backend\.venv 目录后重新双击 start.cmd，让它重建一次。")
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
                & $pythonExecutable -c "import fastapi, uvicorn, sqlalchemy, alembic, pydantic, pydantic_settings, PIL, pypdf, fpdf, websocket, docx, multipart" 2>&1 | Out-Null
                $dependencyProbeExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $probePreference
            }
            if ($dependencyProbeExitCode -ne 0) {
                Write-Host "首次运行：正在安装后端依赖（约 40 个包，第一次要几分钟）..."
                & $pythonExecutable -m pip install `
                    --timeout 300 `
                    --retries 10 `
                    -r (Join-Path $BackendDirectory "requirements.txt")
                if ($LASTEXITCODE -ne 0) {
                    throw ("后端依赖安装失败。`n" +
                        "最常见的原因是网络：默认走官方 PyPI，国内经常很慢或直接超时。`n" +
                        "怎么办（按顺序试）：`n" +
                        "  1) 换国内镜像重装（最有效）：`n" +
                        "     backend\.venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple -r backend\requirements.txt`n" +
                        "  2) 需要代理时，先在 PowerShell 里设好 `$env:HTTP_PROXY / `$env:HTTPS_PROXY 再重试；`n" +
                        "  3) 确认能打开 https://mirrors.aliyun.com/pypi/simple/（打不开就是网络被拦了）；`n" +
                        "  4) 仍失败：把上面 pip 的报错原文发到 GitHub Issues。")
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
            Write-Host "后端已启动：$BackendUrl"
        }

        $frontendRecordPattern = Get-ResumeForgeProcessPattern -Service "frontend"
        $frontendRunning = Test-ResumeForgeFrontend -Url $FrontendUrl
        if (-not $frontendRunning -and (Test-TcpPortInUse -Port $FrontendPort)) {
            # Same as the backend above: our own leftover Vite process fails the
            # proxied health check once its backend is gone, and it is ours to stop.
            if ($null -eq (Get-ProcessRecordMatch -RecordPath $FrontendPidPath -CommandPattern $frontendRecordPattern)) {
                throw ("端口 $FrontendPort 被另一个前端占用，而且它连的不是本次的后端（所以不会去动它）。`n" +
                "怎么办（二选一）：`n" +
                "  1) 关掉占用该端口的程序；`n" +
                "  2) 换一个端口启动：start.cmd -FrontendPort 5180")
            }
            Write-Warning "上一次运行留下的简历通前端正占着端口 $FrontendPort，先停掉它再启动一个新的。"
            Stop-RecordedProcess -DisplayName "frontend" -RecordPath $FrontendPidPath -CommandPattern $frontendRecordPattern
            Start-Sleep -Milliseconds 800
        }

        if ($frontendRunning) {
            Write-Host "前端已经在运行：$FrontendUrl"
        }
        else {
            $nodeRuntime = Ensure-NodeRuntime
            $npmPath = $nodeRuntime.NpmPath

            $viteCommandPath = Join-Path $FrontendDirectory "node_modules\.bin\vite.cmd"
            if (-not (Test-Path -LiteralPath $viteCommandPath -PathType Leaf)) {
                Write-Host "首次运行：正在安装前端依赖（几百个包，第一次要几分钟）..."
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
                        Write-Warning "没有找到 frontend/package-lock.json，改用 npm install 现场生成一份（这样装出来的版本可能与发布时不同）。"
                        & $npmPath install `
                            --no-audit `
                            --no-fund `
                            --fetch-timeout=1800000 `
                            --fetch-retries=5 `
                            --fetch-retry-mintimeout=20000 `
                            --fetch-retry-maxtimeout=120000
                    }
                    if ($LASTEXITCODE -ne 0) {
                        throw ("前端依赖安装失败。`n" +
                    "可能原因：网络不通、npm 镜像不可达、或磁盘空间不足。`n" +
                    "怎么办：`n" +
                    "  1) 手动重试看完整报错：在 frontend 目录执行 `n" +
                    "     npm install --registry=https://registry.npmmirror.com`n" +
                    "  2) 空间不足时先清理磁盘（node_modules 需要约 400 MB）；`n" +
                    "  3) 需要代理时先设好 `$env:HTTP_PROXY / `$env:HTTPS_PROXY；`n" +
                    "  4) 仍失败：把上面 npm 的报错原文发到 GitHub Issues。")
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
            Write-Host "前端已启动：$FrontendUrl"
        }

        if (-not $NoBrowser) {
            # A machine without a default-browser association makes this throw,
            # and the catch below would then tear down the services we just
            # started. Failing to open a window is not a reason to stop the app.
            try {
                Start-Process $FrontendUrl
            }
            catch {
                Write-Warning "没能自动打开浏览器，请手动访问 $FrontendUrl"
            }
        }

        Write-Host "`n简历通已就绪。要关闭服务，双击 stop.cmd。"
    }
    catch {
        Stop-StartedProcess -Process $startedFrontend
        Stop-StartedProcess -Process $startedBackend
        if ($null -ne $startedFrontend) { Remove-Item -LiteralPath $FrontendPidPath -Force -ErrorAction SilentlyContinue }
        if ($null -ne $startedBackend) { Remove-Item -LiteralPath $BackendPidPath -Force -ErrorAction SilentlyContinue }
        throw
    }
}
