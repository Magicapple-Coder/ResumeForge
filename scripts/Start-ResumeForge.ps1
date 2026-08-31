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

function Test-PythonCandidate {
    param(
        [string]$Path,
        [string[]]$PrefixArguments = @()
    )

    $arguments = @($PrefixArguments) + @(
        "-c",
        "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    )
    try {
        & $Path @arguments *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
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

function Find-SystemPython {
    # Prefer the official Windows launcher because python.exe may only be the
    # Microsoft Store execution alias and cannot create a virtual environment.
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $launcher -and (Test-PythonCandidate -Path $launcher.Source -PrefixArguments @("-3"))) {
        return [pscustomobject]@{
            Path            = $launcher.Source
            PrefixArguments = @("-3")
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($env:LocalAppData)) {
        $knownLauncherPath = Join-Path $env:LocalAppData "Programs\Python\Launcher\py.exe"
        if ((Test-Path -LiteralPath $knownLauncherPath) -and
            (Test-PythonCandidate -Path $knownLauncherPath -PrefixArguments @("-3"))) {
            return [pscustomobject]@{
                Path            = $knownLauncherPath
                PrefixArguments = @("-3")
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

        Write-Host "Python was not found. Trying a per-user installation through Windows winget..."
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
            Write-Warning "winget could not install Python (exit code $wingetExitCode). Trying the official Python installer."
            return $false
        }

        Refresh-ProcessPath
        return $true
    }
    catch {
        Write-Warning "Could not use winget to install Python: $($_.Exception.Message)"
        return $false
    }
}

function Install-PythonWithOfficialInstaller {
    $architecture = Get-WindowsArchitecture
    if ($architecture -notin @("AMD64", "X64", "X86_64")) {
        throw "Windows architecture '$architecture' is not supported by the bundled fallback installer (x64 only). Enable winget or install Python 3.10+ manually from https://www.python.org/downloads/windows/."
    }

    $temporaryFile = [IO.Path]::GetTempFileName()
    Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
    $installerPath = "$temporaryFile.exe"

    try {
        Write-Host "Downloading the verified Python $PythonBootstrapVersion installer (about 26 MB) from python.org..."
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
            throw "Could not download the official Python installer. Check the network or proxy settings. $($_.Exception.Message)"
        }

        if (-not (Test-Path -LiteralPath $installerPath)) {
            throw "The downloaded Python installer was not found."
        }

        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash.ToLowerInvariant()
        if ($actualHash -ne $PythonBootstrapSha256) {
            throw "Python installer verification failed; execution was stopped (expected SHA-256: $PythonBootstrapSha256; actual: $actualHash)."
        }

        Write-Host "Verification passed. Installing Python silently for the current user..."
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
            throw "The Python installer failed (exit code $($installerProcess.ExitCode))."
        }
        if ($installerProcess.ExitCode -eq 3010) {
            Write-Warning "Python installed successfully, but Windows requested a restart. The launcher will try to continue."
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

    $wingetSucceeded = Try-InstallPythonWithWinget
    if ($wingetSucceeded) {
        Refresh-ProcessPath
        $systemPython = Find-SystemPython
        if ($null -ne $systemPython) {
            return $systemPython
        }
        Write-Warning "winget reported success, but this process still cannot find Python. Trying the official installer."
    }

    try {
        Install-PythonWithOfficialInstaller
    }
    catch {
        throw "Unable to prepare Python 3.10+ automatically: $($_.Exception.Message) If network, policy, or permissions prevent this, install Python manually from https://www.python.org/downloads/windows/ and run start.cmd again."
    }

    Refresh-ProcessPath
    $systemPython = Find-SystemPython
    if ($null -eq $systemPython) {
        throw "The Python installer finished, but no usable Python 3.10+ was found. Restart start.cmd; if it still fails, install the Python Launcher and disable the Microsoft Store execution alias."
    }
    return $systemPython
}

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

function Stop-StartedProcess {
    param(
        [AllowNull()]
        [System.Diagnostics.Process]$Process
    )

    if ($null -eq $Process) {
        return
    }
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
