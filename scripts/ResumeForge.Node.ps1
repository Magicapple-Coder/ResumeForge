# ResumeForge launcher: Node.js/npm discovery and bootstrap.

function Get-NodeVersion {
    param([string]$NodePath)

    if ([string]::IsNullOrWhiteSpace($NodePath) -or
        -not (Test-Path -LiteralPath $NodePath -PathType Leaf)) {
        return $null
    }

    try {
        $versionText = & $NodePath --version 2> $null | Select-Object -First 1
        # Some winget portable executables report -1 through PowerShell 5.1's
        # LASTEXITCODE even though the process succeeds. A strict version parse
        # is a more reliable probe than that shell-specific exit-code artifact.
        # The bogus code is then cleared so it cannot leak to callers: wrappers
        # that run the launcher through `-Command` (GitHub Actions, for one)
        # exit with whatever is left here, reporting a successful launch as a
        # failure. Whether this probe succeeded is decided by the parse below.
        $global:LASTEXITCODE = 0
        if ([string]::IsNullOrWhiteSpace($versionText)) {
            return $null
        }

        $parsedVersion = $null
        $normalizedVersion = $versionText.Trim() -replace "^v", ""
        if (-not [Version]::TryParse($normalizedVersion, [ref]$parsedVersion)) {
            return $null
        }
        return $parsedVersion
    }
    catch {
        return $null
    }
}

function Test-NodeRuntimeCandidate {
    param(
        [string]$NodePath,
        [string]$NpmPath
    )

    if ([string]::IsNullOrWhiteSpace($NpmPath) -or
        -not (Test-Path -LiteralPath $NpmPath -PathType Leaf)) {
        return $false
    }

    $nodeVersion = Get-NodeVersion -NodePath $NodePath
    if ($null -eq $nodeVersion -or $nodeVersion -lt $MinimumNodeVersion) {
        return $false
    }

    try {
        $npmVersionText = & $NpmPath --version 2> $null | Select-Object -First 1
        # Same reason as the Node.js probe above: npm is only asked for its
        # version here, so its exit code must not decide how callers see the run.
        $global:LASTEXITCODE = 0
        return -not [string]::IsNullOrWhiteSpace($npmVersionText) -and
            $npmVersionText.Trim() -match "^\d+\.\d+\.\d+"
    }
    catch {
        return $false
    }
}

function New-NodeRuntimeRecord {
    param(
        [string]$NodePath,
        [string]$NpmPath
    )

    Add-ProcessPathEntry -Path (Split-Path -Parent $NodePath)
    $nodeVersion = Get-NodeVersion -NodePath $NodePath
    return [pscustomobject]@{
        NodePath = $NodePath
        NpmPath  = $NpmPath
        Version  = $nodeVersion
    }
}

function Find-SystemNodeRuntime {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -ne $nodeCommand -and $null -ne $npmCommand -and
        [string]::Equals(
            (Split-Path -Parent $nodeCommand.Source).TrimEnd("\"),
            (Split-Path -Parent $npmCommand.Source).TrimEnd("\"),
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        (Test-NodeRuntimeCandidate -NodePath $nodeCommand.Source -NpmPath $npmCommand.Source)) {
        return New-NodeRuntimeRecord -NodePath $nodeCommand.Source -NpmPath $npmCommand.Source
    }

    $candidateDirectories = @()
    if ($null -ne $nodeCommand) {
        $candidateDirectories += Split-Path -Parent $nodeCommand.Source
    }
    if ($null -ne $npmCommand) {
        $candidateDirectories += Split-Path -Parent $npmCommand.Source
    }
    if (-not [string]::IsNullOrWhiteSpace($env:NVM_SYMLINK)) {
        $candidateDirectories += $env:NVM_SYMLINK
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LocalAppData)) {
        $candidateDirectories += Join-Path $env:LocalAppData "Programs\nodejs"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidateDirectories += Join-Path $env:ProgramFiles "nodejs"
    }
    if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
        $candidateDirectories += Join-Path ${env:ProgramFiles(x86)} "nodejs"
    }

    foreach ($architectureName in @("x64", "arm64")) {
        $candidateDirectories += Join-Path $NodeToolsDirectory "node-v$NodeBootstrapVersion-win-$architectureName"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LocalAppData)) {
        $wingetNodePattern = Join-Path $env:LocalAppData "Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_*\node-v*-win-*\node.exe"
        $candidateDirectories += Get-ChildItem -Path $wingetNodePattern -File -ErrorAction SilentlyContinue |
            ForEach-Object { $_.DirectoryName }
    }

    foreach ($candidateDirectory in ($candidateDirectories | Select-Object -Unique)) {
        $candidateNodePath = Join-Path $candidateDirectory "node.exe"
        $candidateNpmPath = Join-Path $candidateDirectory "npm.cmd"
        if (Test-NodeRuntimeCandidate -NodePath $candidateNodePath -NpmPath $candidateNpmPath) {
            return New-NodeRuntimeRecord -NodePath $candidateNodePath -NpmPath $candidateNpmPath
        }
    }

    return $null
}

function Try-InstallNodeWithWinget {
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

        Write-Host "没有找到可用的 Node.js/npm，正在尝试用 Windows 自带的 winget 为当前用户安装..."
        & $wingetPath install `
            --id OpenJS.NodeJS.LTS `
            --exact `
            --version $NodeBootstrapVersion `
            --source winget `
            --scope user `
            --silent `
            --accept-source-agreements `
            --accept-package-agreements *> $null
        $wingetExitCode = $LASTEXITCODE
        if ($wingetExitCode -ne 0) {
            Write-Warning "winget 装不上 Node.js（退出码 $wingetExitCode），改用经过校验的便携版运行时。"
            return $false
        }

        Refresh-ProcessPath
        return $true
    }
    catch {
        Write-Warning "winget 无法用来安装 Node.js：$($_.Exception.Message)"
        return $false
    }
}

function Get-NodeBootstrapPackage {
    $architecture = Get-WindowsArchitecture
    if ($architecture -in @("AMD64", "X64", "X86_64")) {
        return [pscustomobject]@{
            Architecture = "x64"
            Url          = $NodeBootstrapX64Url
            Urls         = Get-NodeBootstrapUrls -OfficialUrl $NodeBootstrapX64Url -Architecture "x64"
            Sha256       = $NodeBootstrapX64Sha256
        }
    }
    if ($architecture -eq "ARM64") {
        return [pscustomobject]@{
            Architecture = "arm64"
            Url          = $NodeBootstrapArm64Url
            Urls         = Get-NodeBootstrapUrls -OfficialUrl $NodeBootstrapArm64Url -Architecture "arm64"
            Sha256       = $NodeBootstrapArm64Sha256
        }
    }

    throw ("当前 Windows 架构（$architecture）没有随附的便携版 Node.js。`n" +
            "怎么办：到 https://nodejs.org/ 手动安装 Node.js $MinimumNodeVersion 或更新版本，`n" +
            "装好后重新双击 start.cmd。")
}

function Get-NodeBootstrapUrls {
    param(
        [string]$OfficialUrl,
        [string]$Architecture
    )

    # Domestic mirrors first, official last. Order matters: nodejs.org is
    # routinely unreachable from China, and the old code would sit on a stalled
    # connection for an hour before trying anything else.
    $archiveName = "node-v$NodeBootstrapVersion-win-$Architecture.zip"
    $urls = @()
    foreach ($baseUrl in $NodeBootstrapMirrorBaseUrls) {
        $urls += "$baseUrl/v$NodeBootstrapVersion/$archiveName"
    }
    $urls += $OfficialUrl
    return $urls
}

function Install-PortableNodeRuntime {
    $package = Get-NodeBootstrapPackage
    $archiveBaseName = "node-v$NodeBootstrapVersion-win-$($package.Architecture)"
    $portableDirectory = Join-Path $NodeToolsDirectory $archiveBaseName
    $portableNodePath = Join-Path $portableDirectory "node.exe"
    $portableNpmPath = Join-Path $portableDirectory "npm.cmd"
    if (Test-NodeRuntimeCandidate -NodePath $portableNodePath -NpmPath $portableNpmPath) {
        return
    }

    New-Item -ItemType Directory -Path $NodeToolsDirectory -Force | Out-Null
    $temporaryArchive = [IO.Path]::GetTempFileName()
    Remove-Item -LiteralPath $temporaryArchive -Force -ErrorAction SilentlyContinue
    $temporaryArchive = "$temporaryArchive.zip"
    $stagingDirectory = Join-Path $NodeToolsDirectory ("node-bootstrap-" + [Guid]::NewGuid().ToString("N"))

    try {
        Write-Host "正在下载经过校验的便携版 Node.js $NodeBootstrapVersion 运行时（约 37 MB）..."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        }
        catch {
            # The download still fails safely if an older Windows build cannot
            # negotiate the protocol required by nodejs.org.
        }

        # Try each candidate until one yields a file that matches the pinned
        # hash, under a single overall budget. Without the budget a dead network
        # looks like a hang: the previous code allowed two one-hour attempts per
        # URL. The expected hash is a constant in this repo rather than anything
        # the mirror supplies, so a mirror can only be stale or slow, never
        # substitute content.
        $downloadError = $null
        $downloadDeadline = (Get-Date).AddSeconds($NodeDownloadTotalBudgetSeconds)
        foreach ($candidateUrl in $package.Urls) {
            $remainingSeconds = [int][Math]::Floor(($downloadDeadline - (Get-Date)).TotalSeconds)
            if ($remainingSeconds -le 30) {
                $downloadError = "The download budget of $NodeDownloadTotalBudgetSeconds seconds was exhausted."
                break
            }
            $attemptTimeout = [Math]::Min($NodeDownloadAttemptTimeoutSeconds, $remainingSeconds)
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $candidateUrl -OutFile $temporaryArchive -TimeoutSec $attemptTimeout
            }
            catch {
                $downloadError = "$candidateUrl failed: $($_.Exception.Message)"
                Remove-Item -LiteralPath $temporaryArchive -Force -ErrorAction SilentlyContinue
                Write-Warning "从 $candidateUrl 下载 Node.js 失败，换下一个源..."
                continue
            }

            $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporaryArchive).Hash.ToLowerInvariant()
            if ($actualHash -ne $package.Sha256) {
                # A mirror serving different bytes is worth saying out loud, and
                # the next candidate is very likely fine.
                $downloadError = "$candidateUrl returned a file whose SHA-256 does not match (expected $($package.Sha256); actual $actualHash)."
                Write-Warning $downloadError
                Remove-Item -LiteralPath $temporaryArchive -Force -ErrorAction SilentlyContinue
                continue
            }
            $downloadError = $null
            break
        }
        if ($null -ne $downloadError) {
            throw ("所有下载源都没能拿到 Node.js 运行时。`n" +
            "可能原因：网络不通、公司代理、或安全软件拦截了下载。`n" +
            "怎么办：`n" +
            "  1) 用浏览器打开 https://mirrors.huaweicloud.com/nodejs/ 确认能否访问；`n" +
            "  2) 需要代理时，先在 PowerShell 里设好 `$env:HTTP_PROXY / `$env:HTTPS_PROXY 再重试；`n" +
            "  3) 也可以自己到 https://nodejs.org/ 装好 Node.js $MinimumNodeVersion 或更新版本后重新双击 start.cmd。`n" +
            "原始错误：$downloadError")
        }

        New-Item -ItemType Directory -Path $stagingDirectory -Force | Out-Null
        Expand-Archive -LiteralPath $temporaryArchive -DestinationPath $stagingDirectory
        $extractedDirectory = Join-Path $stagingDirectory $archiveBaseName
        $extractedNodePath = Join-Path $extractedDirectory "node.exe"
        $extractedNpmPath = Join-Path $extractedDirectory "npm.cmd"
        if (-not (Test-NodeRuntimeCandidate -NodePath $extractedNodePath -NpmPath $extractedNpmPath)) {
            throw "下载到的 Node.js 压缩包里没有可用的 node/npm，可能下载不完整。请重试，或手动安装 Node.js $MinimumNodeVersion 或更新版本。"
        }

        if (Test-Path -LiteralPath $portableDirectory) {
            Remove-Item -LiteralPath $portableDirectory -Recurse -Force
        }
        Move-Item -LiteralPath $extractedDirectory -Destination $portableDirectory
    }
    finally {
        Remove-Item -LiteralPath $temporaryArchive -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-NodeRuntime {
    Refresh-ProcessPath
    $nodeRuntime = Find-SystemNodeRuntime
    if ($null -ne $nodeRuntime) {
        return $nodeRuntime
    }

    $wingetSucceeded = Try-InstallNodeWithWinget
    if ($wingetSucceeded) {
        Refresh-ProcessPath
        $nodeRuntime = Find-SystemNodeRuntime
        if ($null -ne $nodeRuntime) {
            return $nodeRuntime
        }
        Write-Warning "winget 报告安装成功，但当前进程仍然找不到可用的 Node.js/npm，改用便携版运行时。"
    }

    try {
        Install-PortableNodeRuntime
    }
    catch {
        throw ("无法自动准备 Node.js/npm：$($_.Exception.Message)`n" +
            "怎么办：`n" +
            "  1) 确认能打开 https://nodejs.org/（国内可用 https://mirrors.huaweicloud.com/nodejs/）；`n" +
            "  2) 手动安装 Node.js $MinimumNodeVersion 或更新版本；`n" +
            "  3) 装完关掉这个窗口，重新双击 start.cmd。")
    }

    $nodeRuntime = Find-SystemNodeRuntime
    if ($null -eq $nodeRuntime) {
        throw ("Node.js 安装流程跑完了，但系统里仍然找不到可用的 Node.js/npm。`n" +
            "怎么办：`n" +
            "  1) 关掉这个窗口，重新双击 start.cmd（安装后需要新进程才能看到新装的 Node.js）；`n" +
            "  2) 仍失败：到 https://nodejs.org/ 手动安装 Node.js $MinimumNodeVersion 或更新版本。")
    }
    return $nodeRuntime
}
