# ResumeForge launcher: Python discovery and bootstrap.

function Test-PythonCandidate {
    param(
        [string]$Path,
        [string[]]$PrefixArguments = @()
    )

    $arguments = @($PrefixArguments) + @("-c", $PythonVersionProbe)
    # A probe must not install anything. The py launcher honours
    # PYLAUNCHER_ALLOW_INSTALL, so if that variable is set in the user's
    # environment, probing an absent version such as -3.13 would silently
    # install it through winget. Remove it for the duration of the probe and
    # restore it afterwards; installing stays in Try-InstallPythonWithWinget,
    # which is deliberate and reports what it is doing.
    $previousAllowInstall = $env:PYLAUNCHER_ALLOW_INSTALL
    try {
        if (-not [string]::IsNullOrEmpty($previousAllowInstall)) {
            Remove-Item Env:PYLAUNCHER_ALLOW_INSTALL -ErrorAction SilentlyContinue
        }
        & $Path @arguments *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        if (-not [string]::IsNullOrEmpty($previousAllowInstall)) {
            $env:PYLAUNCHER_ALLOW_INSTALL = $previousAllowInstall
        }
    }
}

function Test-VenvVersionSupported {
    param([string]$ConfigPath)

    # pyvenv.cfg records the interpreter that built the environment. A venv
    # created by an out-of-window interpreter can never install the pinned
    # wheels, so reusing it makes every run fail the same way. Compare
    # major.minor only: the file writes "3.12.2", the window is 3.10..3.13.
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        return $false
    }
    $versionLine = Get-Content -LiteralPath $ConfigPath -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^\s*version\s*=" } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($versionLine)) {
        return $false
    }
    $parsedVersion = $null
    $rawVersion = ($versionLine -replace "^\s*version\s*=\s*", "").Trim()
    if (-not [Version]::TryParse($rawVersion, [ref]$parsedVersion)) {
        return $false
    }
    $majorMinor = [Version]::new($parsedVersion.Major, $parsedVersion.Minor)
    return ($majorMinor -ge $MinimumPythonVersion -and $majorMinor -le $MaximumPythonVersion)
}

function Format-PythonWindow {
    return "$($MinimumPythonVersion.ToString(2))-$($MaximumPythonVersion.ToString(2))"
}

function Refresh-ProcessPath {
    # Installers update the registry, but the current PowerShell process keeps
    # its old PATH. Merge registry values back into this process before probing
    # for the newly installed interpreter.
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $pathEntries = @()

    foreach ($pathValue in @($userPath, $machinePath, $env:Path)) {
        if ([string]::IsNullOrWhiteSpace($pathValue)) {
            continue
        }
        foreach ($pathEntry in ($pathValue -split ";")) {
            $normalizedEntry = $pathEntry.Trim()
            if (-not [string]::IsNullOrWhiteSpace($normalizedEntry) -and
                -not ($pathEntries -contains $normalizedEntry)) {
                $pathEntries += $normalizedEntry
            }
        }
    }

    if ($pathEntries.Count -gt 0) {
        $env:Path = $pathEntries -join ";"
    }
}

function Add-ProcessPathEntry {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    $normalizedPath = $Path.Trim().TrimEnd("\")
    $remainingEntries = @($env:Path -split ";" | Where-Object {
            -not [string]::IsNullOrWhiteSpace($_) -and
            $_.Trim().TrimEnd("\") -ne $normalizedPath
        })
    $env:Path = (@($normalizedPath) + $remainingEntries) -join ";"
}

function Find-PythonViaLauncher {
    param([string]$LauncherPath)

    # Ask the launcher for each supported version in turn. Probing plain "-3"
    # would hand back the newest interpreter on the machine, which on a box with
    # only 3.14 installed is exactly the one that cannot install the pins.
    foreach ($selector in $PythonSupportedSelectors) {
        if (Test-PythonCandidate -Path $LauncherPath -PrefixArguments @($selector)) {
            return [pscustomobject]@{
                Path            = $LauncherPath
                PrefixArguments = @($selector)
            }
        }
    }
    return $null
}

function Find-SystemPython {
    # Prefer the official Windows launcher because python.exe may only be the
    # Microsoft Store execution alias and cannot create a virtual environment.
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $found = Find-PythonViaLauncher -LauncherPath $launcher.Source
        if ($null -ne $found) {
            return $found
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($env:LocalAppData)) {
        $knownLauncherPath = Join-Path $env:LocalAppData "Programs\Python\Launcher\py.exe"
        if (Test-Path -LiteralPath $knownLauncherPath) {
            $found = Find-PythonViaLauncher -LauncherPath $knownLauncherPath
            if ($null -ne $found) {
                return $found
            }
        }
    }

    foreach ($commandName in @("python.exe", "python3.exe")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        # Do not invoke the Microsoft Store execution alias as a candidate;
        # it is a redirect stub rather than a Python interpreter.
        if ($null -ne $command -and
            $command.Source -notmatch "\\WindowsApps\\python(?:3)?\.exe$") {
            if (-not (Test-PythonCandidate -Path $command.Source)) {
                continue
            }
            return [pscustomobject]@{
                Path            = $command.Source
                PrefixArguments = @()
            }
        }
    }

    # User-level Python installs are not always added to PATH immediately,
    # especially when the launcher is started from an existing Explorer window.
    $knownPythonPatterns = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LocalAppData)) {
        $knownPythonPatterns += Join-Path $env:LocalAppData "Programs\Python\Python*\python.exe"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $knownPythonPatterns += Join-Path $env:ProgramFiles "Python*\python.exe"
    }
    if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
        $knownPythonPatterns += Join-Path ${env:ProgramFiles(x86)} "Python*\python.exe"
    }
    $knownPythonPatterns += "C:\Python*\python.exe"
    foreach ($pythonPattern in $knownPythonPatterns) {
        $directCandidates = Get-ChildItem -Path $pythonPattern -File -ErrorAction SilentlyContinue |
            Sort-Object -Property FullName -Descending
        foreach ($candidate in $directCandidates) {
            if (Test-PythonCandidate -Path $candidate.FullName) {
                return [pscustomobject]@{
                    Path            = $candidate.FullName
                    PrefixArguments = @()
                }
            }
        }
    }

    $knownPythonRoots = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LocalAppData)) {
        $knownPythonRoots += Join-Path $env:LocalAppData "Programs\Python"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $knownPythonRoots += Join-Path $env:ProgramFiles "Python"
    }
    if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
        $knownPythonRoots += Join-Path ${env:ProgramFiles(x86)} "Python"
    }

    foreach ($pythonRoot in $knownPythonRoots) {
        $pythonDirectories = Get-ChildItem -Path $pythonRoot -Directory -Filter "Python*" -ErrorAction SilentlyContinue |
            Sort-Object -Property Name -Descending
        foreach ($pythonDirectory in $pythonDirectories) {
            $candidatePath = Join-Path $pythonDirectory.FullName "python.exe"
            if (Test-PythonCandidate -Path $candidatePath) {
                return [pscustomobject]@{
                    Path            = $candidatePath
                    PrefixArguments = @()
                }
            }
        }
    }

    return $null
}

function Get-WindowsArchitecture {
    $architecture = $env:PROCESSOR_ARCHITEW6432
    if ([string]::IsNullOrWhiteSpace($architecture)) {
        $architecture = $env:PROCESSOR_ARCHITECTURE
    }
    if ([string]::IsNullOrWhiteSpace($architecture)) {
        try {
            $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        }
        catch {
            $architecture = "unknown"
        }
    }
    return $architecture.ToUpperInvariant()
}

function Try-InstallPythonWithWinget {
    $wingetCommand = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -eq $wingetCommand) {
        return $false
    }

    $wingetPath = $wingetCommand.Source
    if ([string]::IsNullOrWhiteSpace($wingetPath)) {
        $wingetPath = $wingetCommand.Definition
    }

    try {
        & $wingetPath --version *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        Write-Host "没有找到 Python，正在尝试用 Windows 自带的 winget 为当前用户安装..."
        & $wingetPath install `
            --id Python.Python.3.12 `
            --exact `
            --source winget `
            --scope user `
            --silent `
            --accept-source-agreements `
            --accept-package-agreements *> $null
        $wingetExitCode = $LASTEXITCODE
        if ($wingetExitCode -ne 0) {
            Write-Warning "winget 装不上 Python（退出码 $wingetExitCode），改用 Python 官方安装包。"
            return $false
        }

        Refresh-ProcessPath
        return $true
    }
    catch {
        Write-Warning "winget 无法用来安装 Python：$($_.Exception.Message)"
        return $false
    }
}

function Install-PythonWithOfficialInstaller {
    $architecture = Get-WindowsArchitecture
    if ($architecture -notin @("AMD64", "X64", "X86_64")) {
        throw ("当前 Windows 架构（$architecture）没有随附的自动安装包（只提供 x64）。`n" +
            "怎么办：`n" +
            "  1) 打开「设置 → 应用 → 高级应用设置 → 应用执行别名」，确认 Python 的 winget 可用后重试；或`n" +
            "  2) 到 https://www.python.org/downloads/windows/ 手动安装 $(Format-PythonWindow)（安装时勾选 Add python.exe to PATH），`n" +
            "     装好后重新双击 start.cmd。")
    }

    $temporaryFile = [IO.Path]::GetTempFileName()
    Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
    $installerPath = "$temporaryFile.exe"

    try {
        Write-Host "正在从 python.org 下载经过校验的 Python $PythonBootstrapVersion 安装包（约 26 MB）..."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        }
        catch {
            # Older Windows builds may not expose the enum value; the request
            # will still fail safely if the server refuses an older protocol.
        }

        try {
            Invoke-WebRequest -UseBasicParsing -Uri $PythonBootstrapUrl -OutFile $installerPath -TimeoutSec 180
        }
        catch {
            throw ("下载 Python 官方安装包失败。`n" +
            "可能原因：网络不通、公司代理、或安全软件拦截了下载。`n" +
            "怎么办：`n" +
            "  1) 用浏览器打开 https://www.python.org/ftp/python/$PythonBootstrapVersion/python-$PythonBootstrapVersion-amd64.exe 确认能否下载；`n" +
            "  2) 需要代理时，先在 PowerShell 里设好 `$env:HTTP_PROXY / `$env:HTTPS_PROXY 再重试；`n" +
            "  3) 也可以自己装好 Python $(Format-PythonWindow)（勾选 Add python.exe to PATH）后重新双击 start.cmd。`n" +
            "原始错误：$($_.Exception.Message)")
        }

        if (-not (Test-Path -LiteralPath $installerPath)) {
            throw "下载 Python 安装包后没有找到文件（可能被杀毒软件删掉了）。请检查安全软件后重试，或手动安装 Python $(Format-PythonWindow)。"
        }

        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash.ToLowerInvariant()
        if ($actualHash -ne $PythonBootstrapSha256) {
            throw "Python installer verification failed; execution was stopped (expected SHA-256: $PythonBootstrapSha256; actual: $actualHash)."
        }

        Write-Host "校验通过，正在为当前用户静默安装 Python..."
        $installerProcess = Start-Process -FilePath $installerPath `
            -ArgumentList @(
                "/quiet",
                "/norestart",
                "InstallAllUsers=0",
                "PrependPath=1",
                "Include_launcher=1",
                "Include_test=0"
            ) `
            -WindowStyle Hidden `
            -Wait `
            -PassThru

        if ($installerProcess.ExitCode -notin @(0, 3010)) {
            throw ("Python 安装程序执行失败（退出码 $($installerProcess.ExitCode)）。`n" +
            "怎么办：`n" +
            "  1) 手动运行安装包试试，看是否有权限/安全软件的提示；`n" +
            "  2) 或到 https://www.python.org/downloads/windows/ 手动安装 $(Format-PythonWindow)（勾选 Add python.exe to PATH），`n" +
            "     装好后重新双击 start.cmd。")
        }
        if ($installerProcess.ExitCode -eq 3010) {
            Write-Warning "Python 已装好，但 Windows 要求重启后才完全生效。启动器会先继续尝试，若失败请重启电脑后再双击 start.cmd。"
        }
    }
    finally {
        Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-SystemPython {
    Refresh-ProcessPath
    $systemPython = Find-SystemPython
    if ($null -ne $systemPython) {
        return $systemPython
    }

    # An interpreter may exist yet still be outside the window (a machine with
    # only 3.14 installed lands here), so say what we are looking for.
    Write-Host "没有找到受支持的 Python（需要 $(Format-PythonWindow)），正在自动准备一个..."

    $wingetSucceeded = Try-InstallPythonWithWinget
    if ($wingetSucceeded) {
        Refresh-ProcessPath
        $systemPython = Find-SystemPython
        if ($null -ne $systemPython) {
            return $systemPython
        }
        Write-Warning "winget 报告安装成功，但当前进程仍然找不到 Python，改用官方安装包。"
    }

    try {
        Install-PythonWithOfficialInstaller
    }
    catch {
        throw ("无法自动准备 Python $(Format-PythonWindow)：$($_.Exception.Message)`n" +
            "怎么办：`n" +
            "  1) 到 https://www.python.org/downloads/windows/ 手动安装 $(Format-PythonWindow)`n" +
            "     （安装时务必勾选 Add python.exe to PATH）；`n" +
            "  2) 装完关掉这个窗口，重新双击 start.cmd。`n" +
            "注意：本项目目前只支持 Python 3.10 ~ 3.13，3.14 及更新版本还装不上依赖。")
    }

    Refresh-ProcessPath
    $systemPython = Find-SystemPython
    if ($null -eq $systemPython) {
        throw ("Python 安装程序跑完了，但系统里仍然找不到可用的 Python $(Format-PythonWindow)。`n" +
            "最常见的原因有两个：`n" +
            "  1) 本项目的依赖还没有 Python 3.14 的现成包，所以只支持 3.10 ~ 3.13；`n" +
            "  2) Windows 自带的「应用执行别名」把 python 指向了 Microsoft Store。`n" +
            "怎么办：`n" +
            "  1) 关掉这个窗口，重新双击 start.cmd（安装后需要新进程才能看到新装的 Python）；`n" +
            "  2) 仍失败：打开「设置 → 应用 → 高级应用设置 → 应用执行别名」，`n" +
            "     关掉 Python / python3 的别名开关，再重新双击 start.cmd。")
    }
    return $systemPython
}
