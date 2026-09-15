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
        throw "Windows architecture '$architecture' is not supported by the bundled fallback installer (x64 only). Enable winget or install Python $(Format-PythonWindow) manually from https://www.python.org/downloads/windows/."
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

    # An interpreter may exist yet still be outside the window (a machine with
    # only 3.14 installed lands here), so say what we are looking for.
    Write-Host "No supported Python ($(Format-PythonWindow)) found. Preparing one automatically..."

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
        throw "Unable to prepare Python $(Format-PythonWindow) automatically: $($_.Exception.Message) If network, policy, or permissions prevent this, install Python manually from https://www.python.org/downloads/windows/ and run start.cmd again."
    }

    Refresh-ProcessPath
    $systemPython = Find-SystemPython
    if ($null -eq $systemPython) {
        throw "The Python installer finished, but no usable Python $(Format-PythonWindow) was found. Newer interpreters do not work yet: the pinned backend dependencies have no Python 3.14 wheels. Restart start.cmd; if it still fails, install the Python Launcher and disable the Microsoft Store execution alias."
    }
    return $systemPython
}
