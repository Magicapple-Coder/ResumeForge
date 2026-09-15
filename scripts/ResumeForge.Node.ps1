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

        Write-Host "A compatible Node.js/npm runtime was not found. Trying a per-user installation through Windows winget..."
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
            Write-Warning "winget could not install Node.js (exit code $wingetExitCode). Trying the verified portable runtime."
            return $false
        }

        Refresh-ProcessPath
        return $true
    }
    catch {
        Write-Warning "Could not use winget to install Node.js: $($_.Exception.Message)"
        return $false
    }
}

function Get-NodeBootstrapPackage {
    $architecture = Get-WindowsArchitecture
    if ($architecture -in @("AMD64", "X64", "X86_64")) {
        return [pscustomobject]@{
            Architecture = "x64"
            Url          = $NodeBootstrapX64Url
            Sha256       = $NodeBootstrapX64Sha256
        }
    }
    if ($architecture -eq "ARM64") {
        return [pscustomobject]@{
            Architecture = "arm64"
            Url          = $NodeBootstrapArm64Url
            Sha256       = $NodeBootstrapArm64Sha256
        }
    }

    throw "Windows architecture '$architecture' is not supported by the portable Node.js fallback. Enable winget or install Node.js $MinimumNodeVersion or later manually from https://nodejs.org/."
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
        Write-Host "Downloading the verified portable Node.js $NodeBootstrapVersion runtime (about 37 MB) from nodejs.org..."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        }
        catch {
            # The download still fails safely if an older Windows build cannot
            # negotiate the protocol required by nodejs.org.
        }

        $downloadError = $null
        foreach ($downloadAttempt in 1..2) {
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $package.Url -OutFile $temporaryArchive -TimeoutSec 3600
                $downloadError = $null
                break
            }
            catch {
                $downloadError = $_.Exception.Message
                Remove-Item -LiteralPath $temporaryArchive -Force -ErrorAction SilentlyContinue
                if ($downloadAttempt -lt 2) {
                    Write-Warning "The Node.js download was interrupted. Retrying once..."
                }
            }
        }
        if ($null -ne $downloadError) {
            throw "Could not download the official Node.js runtime after two attempts. Check the network or proxy settings. $downloadError"
        }

        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporaryArchive).Hash.ToLowerInvariant()
        if ($actualHash -ne $package.Sha256) {
            throw "Node.js archive verification failed; extraction was stopped (expected SHA-256: $($package.Sha256); actual: $actualHash)."
        }

        New-Item -ItemType Directory -Path $stagingDirectory -Force | Out-Null
        Expand-Archive -LiteralPath $temporaryArchive -DestinationPath $stagingDirectory
        $extractedDirectory = Join-Path $stagingDirectory $archiveBaseName
        $extractedNodePath = Join-Path $extractedDirectory "node.exe"
        $extractedNpmPath = Join-Path $extractedDirectory "npm.cmd"
        if (-not (Test-NodeRuntimeCandidate -NodePath $extractedNodePath -NpmPath $extractedNpmPath)) {
            throw "The verified Node.js archive did not contain a usable Node.js/npm runtime."
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
        Write-Warning "winget reported success, but this process still cannot find compatible Node.js/npm. Trying the portable runtime."
    }

    try {
        Install-PortableNodeRuntime
    }
    catch {
        throw "Unable to prepare Node.js/npm automatically: $($_.Exception.Message) If network or system policy prevents this, install Node.js $MinimumNodeVersion or later from https://nodejs.org/ and run start.cmd again."
    }

    $nodeRuntime = Find-SystemNodeRuntime
    if ($null -eq $nodeRuntime) {
        throw "The Node.js setup finished, but no compatible Node.js/npm runtime was found. Restart start.cmd; if it still fails, install Node.js $MinimumNodeVersion or later manually."
    }
    return $nodeRuntime
}
