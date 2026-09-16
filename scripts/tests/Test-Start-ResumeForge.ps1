[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$LauncherPath = Join-Path $ProjectRoot "scripts\Start-ResumeForge.ps1"
$RuntimeDirectory = Join-Path ([IO.Path]::GetTempPath()) ("resumeforge-launcher-test-" + [Guid]::NewGuid().ToString("N"))
$MinimumNodeVersion = [Version]"20.19.0"
$NodeBootstrapVersion = "24.19.0"
$NodeBootstrapX64Url = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-x64.zip"
$NodeBootstrapX64Sha256 = "57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73"
$NodeBootstrapArm64Url = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-arm64.zip"
$NodeBootstrapArm64Sha256 = "8502f4a50b458d4cc38ed8f2001556c2cd239d464920f74017926ccb1e1c157f"
$NodeToolsDirectory = Join-Path $RuntimeDirectory "tools"
# Mirrors of the constants the launcher defines. The functions loaded below read
# these from the caller's scope, and the assertions further down pin the
# launcher's own copies so the two cannot drift.
$MinimumPythonVersion = [Version]"3.10"
$MaximumPythonVersion = [Version]"3.13"
$PythonVersionProbe = 'import sys; raise SystemExit(0 if ({0}, {1}) <= sys.version_info[:2] <= ({2}, {3}) else 1)' -f `
    $MinimumPythonVersion.Major, $MinimumPythonVersion.Minor, `
    $MaximumPythonVersion.Major, $MaximumPythonVersion.Minor
$PythonSupportedSelectors = @("-3.12", "-3.13", "-3.11", "-3.10")
$BackendStartTimeoutSeconds = 90
$FrontendStartTimeoutSeconds = 120
$NodeBootstrapMirrorBaseUrls = @(
    "https://mirrors.huaweicloud.com/nodejs",
    "https://cdn.npmmirror.com/binaries/node",
    "https://mirrors.cloud.tencent.com/nodejs-release"
)
$NodeDownloadAttemptTimeoutSeconds = 600
$NodeDownloadTotalBudgetSeconds = 1800

function Assert-LauncherTest {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Send-TestDirectoryToRecycleBin {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    try {
        Add-Type -AssemblyName Microsoft.VisualBasic
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(
            $Path,
            [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
            [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin
        )
    }
    catch {
        Write-Warning "Could not move launcher test data to the recycle bin; leaving it in place: $($_.Exception.Message)"
    }
}

$tokens = $null
$parseErrors = $null
$launcherAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $LauncherPath,
    [ref]$tokens,
    [ref]$parseErrors
)
Assert-LauncherTest -Condition ($parseErrors.Count -eq 0) -Message "The launcher has PowerShell syntax errors."
$launcherContent = Get-Content -LiteralPath $LauncherPath -Raw -Encoding utf8
foreach ($requiredSetting in @(
        '$MinimumNodeVersion = [Version]"20.19.0"',
        '$NodeBootstrapVersion = "24.19.0"',
        '$NodeBootstrapX64Sha256 = "57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73"',
        '$NodeBootstrapArm64Sha256 = "8502f4a50b458d4cc38ed8f2001556c2cd239d464920f74017926ccb1e1c157f"',
        '$MinimumPythonVersion = [Version]"3.10"',
        '$MaximumPythonVersion = [Version]"3.13"',
        '$BackendStartTimeoutSeconds = 90',
        '$FrontendStartTimeoutSeconds = 120',
        '$NodeDownloadTotalBudgetSeconds = 1800'
    )) {
    Assert-LauncherTest `
        -Condition $launcherContent.Contains($requiredSetting) `
        -Message "The launcher bootstrap setting is missing or unexpected: $requiredSetting"
}

# UTF-8 mode must be on before the launcher does any work, because pip 24.x
# decodes a BOM-less requirements file with the locale codec.
$utf8Index = $launcherContent.IndexOf('$env:PYTHONUTF8')
$startCallIndex = $launcherContent.IndexOf("`nStart-ResumeForge")
Assert-LauncherTest `
    -Condition ($utf8Index -ge 0 -and $startCallIndex -gt $utf8Index) `
    -Message "The launcher must set PYTHONUTF8 before it starts doing work, so venv creation, pip and uvicorn all inherit it."

# This is the test that would have caught the GBK failure: CI runs under a UTF-8
# locale, so nothing there ever reproduces it.
foreach ($asciiOnlyName in @("requirements.txt", "requirements-dev.txt")) {
    $asciiOnlyPath = Join-Path $ProjectRoot "backend\$asciiOnlyName"
    $nonAsciiCount = @([IO.File]::ReadAllBytes($asciiOnlyPath) | Where-Object { $_ -gt 0x7F }).Count
    Assert-LauncherTest `
        -Condition ($nonAsciiCount -eq 0) `
        -Message "$asciiOnlyName must stay pure ASCII: pip decodes it with the locale codec (cp936 on Chinese Windows) when the file has no BOM."
}

# start.cmd must forward its arguments; the launcher's own port-conflict message
# tells the user to pass -BackendPort, which is impossible without this.
$startCmdContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "start.cmd") -Raw
Assert-LauncherTest `
    -Condition ($startCmdContent -match 'Start-ResumeForge\.ps1"\s+%\*') `
    -Message "start.cmd must forward its arguments with %*."

# Load function definitions without executing the launcher's service startup.
# Helpers now live in focused dot-sourced modules; parse each module directly so
# this characterization test remains independent from network/process startup.
$launcherScriptPaths = @($LauncherPath) + @(
    Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "scripts") -Filter "ResumeForge.*.ps1" -File |
        Select-Object -ExpandProperty FullName
)
$functionDefinitions = @()
foreach ($scriptPath in $launcherScriptPaths) {
    $scriptTokens = $null
    $scriptErrors = $null
    $scriptAst = [System.Management.Automation.Language.Parser]::ParseFile(
        $scriptPath,
        [ref]$scriptTokens,
        [ref]$scriptErrors
    )
    Assert-LauncherTest `
        -Condition ($scriptErrors.Count -eq 0) `
        -Message "Launcher module has PowerShell syntax errors: $scriptPath"
    $functionDefinitions += $scriptAst.FindAll(
        {
            param($node)
            return $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
        },
        $true
    )
}
foreach ($functionDefinition in $functionDefinitions) {
    Invoke-Expression $functionDefinition.Extent.Text
}

New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null
$oldNodePath = Join-Path $RuntimeDirectory "node-old.cmd"
$minimumNodePath = Join-Path $RuntimeDirectory "node-minimum.cmd"
$mockNpmPath = Join-Path $RuntimeDirectory "npm.cmd"
Set-Content -LiteralPath $oldNodePath -Value "@echo v20.18.0" -Encoding ascii
Set-Content -LiteralPath $minimumNodePath -Value "@echo v20.19.0" -Encoding ascii
Set-Content -LiteralPath $mockNpmPath -Value "@echo 11.0.0" -Encoding ascii

try {
    Assert-LauncherTest `
        -Condition (-not (Test-NodeRuntimeCandidate -NodePath $oldNodePath -NpmPath $mockNpmPath)) `
        -Message "Node.js below 20.19.0 must be rejected."

    Assert-LauncherTest `
        -Condition (Test-NodeRuntimeCandidate -NodePath $minimumNodePath -NpmPath $mockNpmPath) `
        -Message "Node.js 20.19.0 with npm must be accepted."

    function Get-WindowsArchitecture { return "AMD64" }
    $x64Package = Get-NodeBootstrapPackage
    Assert-LauncherTest `
        -Condition ($x64Package.Architecture -eq "x64" -and $x64Package.Sha256 -eq $NodeBootstrapX64Sha256) `
        -Message "The x64 Node.js bootstrap package is incorrect."

    function Get-WindowsArchitecture { return "ARM64" }
    $arm64Package = Get-NodeBootstrapPackage
    Assert-LauncherTest `
        -Condition ($arm64Package.Architecture -eq "arm64" -and $arm64Package.Sha256 -eq $NodeBootstrapArm64Sha256) `
        -Message "The ARM64 Node.js bootstrap package is incorrect."

    $script:wingetCalled = $false
    function Refresh-ProcessPath {}
    function Find-SystemNodeRuntime {
        return [pscustomobject]@{
            NodePath = "existing-node.exe"
            NpmPath  = "existing-npm.cmd"
            Version  = [Version]"24.19.0"
        }
    }
    function Try-InstallNodeWithWinget {
        $script:wingetCalled = $true
        return $true
    }
    $existingRuntime = Ensure-NodeRuntime
    Assert-LauncherTest `
        -Condition ($existingRuntime.NodePath -eq "existing-node.exe" -and -not $script:wingetCalled) `
        -Message "An existing compatible Node.js runtime must be reused without installation."

    $script:portableInstalled = $false
    function Find-SystemNodeRuntime {
        if (-not $script:portableInstalled) {
            return $null
        }
        return [pscustomobject]@{
            NodePath = "portable-node.exe"
            NpmPath  = "portable-npm.cmd"
            Version  = [Version]"24.19.0"
        }
    }
    function Try-InstallNodeWithWinget { return $false }
    function Install-PortableNodeRuntime { $script:portableInstalled = $true }
    $portableRuntime = Ensure-NodeRuntime
    Assert-LauncherTest `
        -Condition ($portableRuntime.NodePath -eq "portable-node.exe" -and $script:portableInstalled) `
        -Message "A missing Node.js runtime must use the portable fallback when winget is unavailable."

    # --- Python version window and interpreter selection ---

    # A venv built outside the window can never install the pins, so it must not
    # be reused. Driven by a crafted pyvenv.cfg, so no interpreter is needed.
    $staleVenvConfig = Join-Path $RuntimeDirectory "pyvenv-314.cfg"
    Set-Content -LiteralPath $staleVenvConfig -Encoding ascii -Value @("home = C:\Python314", "version = 3.14.7")
    Assert-LauncherTest `
        -Condition (-not (Test-VenvVersionSupported -ConfigPath $staleVenvConfig)) `
        -Message "A virtual environment built by Python 3.14 must be treated as unusable."
    Set-Content -LiteralPath $staleVenvConfig -Encoding ascii -Value @("home = D:\Python\Python312", "version = 3.12.2")
    Assert-LauncherTest `
        -Condition (Test-VenvVersionSupported -ConfigPath $staleVenvConfig) `
        -Message "A Python 3.12 virtual environment must be reusable."
    Set-Content -LiteralPath $staleVenvConfig -Encoding ascii -Value @("home = C:\Python313")
    Assert-LauncherTest `
        -Condition (-not (Test-VenvVersionSupported -ConfigPath $staleVenvConfig)) `
        -Message "A pyvenv.cfg without a version line must be treated as unusable."

    # The probe must agree with whatever interpreter runs it.
    $hostPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $hostPython -and $hostPython.Source -notmatch "\\WindowsApps\\") {
        $reportedVersion = & $hostPython.Source -c "import sys; print('%d.%d' % sys.version_info[:2])"
        & $hostPython.Source -c $PythonVersionProbe *> $null
        $expectedAccepted = $reportedVersion -in @("3.10", "3.11", "3.12", "3.13")
        Assert-LauncherTest `
            -Condition (($LASTEXITCODE -eq 0) -eq $expectedAccepted) `
            -Message "The Python version probe disagrees with the interpreter it ran on ($reportedVersion)."
    }

    $script:probedSelectors = @()
    function Get-Command {
        param($Name, $ErrorAction)
        if ($Name -eq "py.exe") { return [pscustomobject]@{ Source = "C:\Windows\py.exe" } }
        return $null
    }
    function Test-PythonCandidate {
        param([string]$Path, [string[]]$PrefixArguments = @())
        $selector = ($PrefixArguments -join " ")
        $script:probedSelectors += $selector
        return $selector -eq "-3.12"
    }
    $selectedPython = Find-SystemPython
    Assert-LauncherTest `
        -Condition (($selectedPython.PrefixArguments -join " ") -eq "-3.12") `
        -Message "A supported interpreter must be selected from the launcher."
    Assert-LauncherTest `
        -Condition ($script:probedSelectors[0] -eq "-3.12" -and $script:probedSelectors.Count -eq 1) `
        -Message "Probing must start at 3.12 and stop at the first supported runtime."

    # --- launching npm.cmd from a path that contains spaces ---

    # The frontend used to go through a hand-written "cmd /s /c ""<path>" args"
    # line. Start-Process joins -ArgumentList with spaces and adds no quoting
    # while cmd /s /c strips the outer quotes, so a Node install under
    # "C:\Program Files\nodejs" (the official MSI default) never started. The
    # launcher now hands npm.cmd to Start-Process directly and lets PowerShell
    # build the cmd.exe wrapper, so this runs the same shape against a stub in a
    # directory with a space in its name.
    $spacedDirectory = Join-Path $RuntimeDirectory "program files node"
    New-Item -ItemType Directory -Path $spacedDirectory -Force | Out-Null
    $stubNpmPath = Join-Path $spacedDirectory "npm.cmd"
    $stubMarkerPath = Join-Path $RuntimeDirectory "stub-arguments.txt"
    Set-Content -LiteralPath $stubNpmPath -Encoding ascii -Value @(
        "@echo off",
        "echo %* > `"$stubMarkerPath`"",
        "exit /b 0"
    )

    $stubOutputPath = Join-Path $RuntimeDirectory "stub.stdout.log"
    $stubErrorPath = Join-Path $RuntimeDirectory "stub.stderr.log"
    $spacedProcess = Start-Process -FilePath $stubNpmPath `
        -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort") `
        -WorkingDirectory $RuntimeDirectory -WindowStyle Hidden -Wait -PassThru `
        -RedirectStandardOutput $stubOutputPath -RedirectStandardError $stubErrorPath
    Assert-LauncherTest `
        -Condition ($spacedProcess.ExitCode -eq 0) `
        -Message "npm.cmd could not be started from a path containing a space (exit $($spacedProcess.ExitCode))."
    Assert-LauncherTest `
        -Condition (Test-Path -LiteralPath $stubMarkerPath) `
        -Message "The npm.cmd stub never ran, so the command line was misparsed."
    Assert-LauncherTest `
        -Condition ((Get-Content -LiteralPath $stubMarkerPath -Raw) -match "run dev -- --host 127\.0\.0\.1 --port 5173 --strictPort") `
        -Message "Arguments were mangled on the way to npm.cmd."

    # stop.cmd finds the frontend by matching the recorded command line, so the
    # wrapper PowerShell builds must still contain the npm.cmd invocation. Use
    # the same spaced npm.cmd stub, kept alive long enough to be inspected, and
    # stop it before asserting so a failure cannot strand the process tree.
    Set-Content -LiteralPath $stubNpmPath -Encoding ascii -Value @("@echo off", "ping -n 60 127.0.0.1 > nul")
    $longStubProcess = Start-Process -FilePath $stubNpmPath -ArgumentList @("run", "dev") `
        -WorkingDirectory $RuntimeDirectory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $RuntimeDirectory "tree.stdout.log") `
        -RedirectStandardError (Join-Path $RuntimeDirectory "tree.stderr.log")
    Start-Sleep -Seconds 2
    $stubRecord = Get-CimInstance Win32_Process -Filter "ProcessId = $($longStubProcess.Id)"
    $stubProcessName = $stubRecord.Name
    $stubCommandLine = $stubRecord.CommandLine
    Stop-StartedProcess -Process $longStubProcess
    Start-Sleep -Milliseconds 800

    Assert-LauncherTest `
        -Condition ($stubProcessName -eq "cmd.exe") `
        -Message "The recorded frontend process must stay cmd.exe, or stop.cmd will not recognise it."
    Assert-LauncherTest `
        -Condition ($stubCommandLine -match "npm\.cmd.*\brun\s+dev") `
        -Message "stop.cmd identifies the frontend by matching its command line; that match broke."

    # --- Node download candidates ---

    function Get-WindowsArchitecture { return "AMD64" }
    $x64Package = Get-NodeBootstrapPackage
    Assert-LauncherTest `
        -Condition ($x64Package.Urls.Count -ge 2) `
        -Message "A mirror list plus the official fallback is expected."
    Assert-LauncherTest `
        -Condition ($x64Package.Urls[-1] -eq $NodeBootstrapX64Url) `
        -Message "nodejs.org must remain the last download candidate."
    Assert-LauncherTest `
        -Condition ($x64Package.Urls[0] -notmatch "nodejs\.org") `
        -Message "A domestic mirror must be tried before nodejs.org."
    Assert-LauncherTest `
        -Condition (@($x64Package.Urls | Where-Object { $_ -notmatch "^https://" }).Count -eq 0) `
        -Message "Every download candidate must use https."
    Assert-LauncherTest `
        -Condition (@($x64Package.Urls | Where-Object { $_ -notmatch "node-v24\.19\.0-win-x64\.zip$" }).Count -eq 0) `
        -Message "Every candidate must point at the archive the pinned SHA-256 covers."

    # --- wait/stop behaviour ---

    $exitedProcess = Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/c", "exit 0") -WindowStyle Hidden -Wait -PassThru
    $waitWatch = [Diagnostics.Stopwatch]::StartNew()
    $waitResult = Wait-ForCondition -Condition { $false } -TimeoutSeconds 30 -FailFastProcess $exitedProcess
    $waitWatch.Stop()
    Assert-LauncherTest `
        -Condition (-not $waitResult -and $waitWatch.Elapsed.TotalSeconds -lt 5) `
        -Message "Wait-ForCondition must stop as soon as the child has exited (took $($waitWatch.Elapsed.TotalSeconds) s)."

    $liveProcess = Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/c", "ping -n 30 127.0.0.1 > nul") -WindowStyle Hidden -PassThru
    $waitWatch.Restart()
    $timeoutResult = Wait-ForCondition -Condition { $false } -TimeoutSeconds 5 -FailFastProcess $liveProcess
    $waitWatch.Stop()
    Assert-LauncherTest `
        -Condition (-not $timeoutResult -and $waitWatch.Elapsed.TotalSeconds -ge 4.5) `
        -Message "The TimeoutSeconds parameter must be honoured."

    $treeStubPath = Join-Path $RuntimeDirectory "tree.cmd"
    Set-Content -LiteralPath $treeStubPath -Encoding ascii -Value @(
        "@echo off",
        "start /b cmd.exe /c `"ping -n 300 127.0.0.1 > nul`"",
        "ping -n 300 127.0.0.1 > nul"
    )
    $treeProcess = Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/s", "/c", $treeStubPath) -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    $treeChildren = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($treeProcess.Id)")
    Stop-StartedProcess -Process $treeProcess
    Stop-StartedProcess -Process $liveProcess
    Start-Sleep -Milliseconds 1500
    $treeSurvivors = @($treeChildren | Where-Object { $null -ne (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue) })
    Assert-LauncherTest `
        -Condition ($treeSurvivors.Count -eq 0) `
        -Message "Stop-StartedProcess left the cmd tree running; the port would stay bound."

    # --- identifying our own processes ---

    Assert-LauncherTest `
        -Condition ("uvicorn app.main:app --host 127.0.0.1 --port 8005" -match (Get-ResumeForgeProcessPattern -Service "backend")) `
        -Message "The backend pattern must match the command line the launcher starts."
    Assert-LauncherTest `
        -Condition ("cmd.exe /d /s /c `"C:\Program Files\nodejs\npm.cmd`" run dev -- --host 127.0.0.1" -match (Get-ResumeForgeProcessPattern -Service "frontend")) `
        -Message "The frontend pattern must match the cmd.exe wrapper PowerShell builds around npm.cmd."

    # --- failure messages must carry the cause ---

    # A real report: an incomplete zip made the backend die at import time, and the
    # only output was "Backend exited with code  before becoming healthy. See
    # runtime\backend.stderr.log." -- a blank exit code and no cause to act on.
    $failureLogPath = Join-Path $RuntimeDirectory "backend.stderr.log"
    Set-Content -LiteralPath $failureLogPath -Encoding utf8 -Value @(
        "",
        "INFO:     Started server process",
        "",
        "RuntimeError: incomplete installation"
    )
    $tail = @(Get-LogTail -Path $failureLogPath)
    Assert-LauncherTest `
        -Condition ($tail.Count -eq 2) `
        -Message "Get-LogTail must drop blank lines (got $($tail.Count))."
    Assert-LauncherTest `
        -Condition ($tail[-1] -like "*incomplete installation*") `
        -Message "Get-LogTail must keep the last line."
    $limitedTail = @(Get-LogTail -Path $failureLogPath -LineCount 1)
    Assert-LauncherTest `
        -Condition ($limitedTail.Count -eq 1 -and $limitedTail[0] -like "*incomplete installation*") `
        -Message "Get-LogTail must honour LineCount."
    Assert-LauncherTest `
        -Condition (@(Get-LogTail -Path (Join-Path $RuntimeDirectory "no-such.log")).Count -eq 0) `
        -Message "A missing log file must yield an empty tail instead of an error."

    $exitedStub = Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/c", "exit 7") -WindowStyle Hidden -Wait -PassThru
    Assert-LauncherTest `
        -Condition ((Get-ProcessExitCodeText -Process $exitedStub) -eq "7") `
        -Message "Get-ProcessExitCodeText must report the real exit code."

    $liveStub = Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/c", "ping -n 30 127.0.0.1 > nul") -WindowStyle Hidden -PassThru
    $liveExitCodeText = Get-ProcessExitCodeText -Process $liveStub
    $failureMessage = Format-ServiceStartFailure `
        -DisplayName "Backend" `
        -Reason "exited with code $liveExitCodeText before becoming healthy" `
        -LogPath $failureLogPath
    Stop-StartedProcess -Process $liveStub
    Assert-LauncherTest `
        -Condition ($liveExitCodeText -eq "unknown") `
        -Message "A process that has not exited has no exit code; the text must not be empty."
    Assert-LauncherTest `
        -Condition ($failureMessage.Contains($failureLogPath) -and $failureMessage -like "*incomplete installation*") `
        -Message "The failure message must name the log and print its tail."

    # --- only our own recorded processes are ever stopped ---

    $stubRecordPath = Join-Path $RuntimeDirectory "recorded-stub.json"
    $stubProcess = Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/c", "ping -n 60 127.0.0.1 > nul") -WindowStyle Hidden -PassThru
    Save-ProcessRecord -Process $stubProcess -Path $stubRecordPath
    # cmd.exe cannot carry the real uvicorn command line, so match on its own.
    $cmdPattern = "cmd\.exe"
    Assert-LauncherTest `
        -Condition ($null -ne (Get-ProcessRecordMatch -RecordPath $stubRecordPath -CommandPattern $cmdPattern)) `
        -Message "A record written for a live process must match it."
    Assert-LauncherTest `
        -Condition ($null -eq (Get-ProcessRecordMatch -RecordPath $stubRecordPath -CommandPattern "uvicorn")) `
        -Message "A record must not match when the command line disagrees."

    Stop-RecordedProcess -DisplayName "stub backend" -RecordPath $stubRecordPath -CommandPattern $cmdPattern
    Assert-LauncherTest `
        -Condition (-not (Test-Path -LiteralPath $stubRecordPath)) `
        -Message "Stop-RecordedProcess must remove the record it acted on."
    Assert-LauncherTest `
        -Condition ($null -eq (Get-Process -Id $stubProcess.Id -ErrorAction SilentlyContinue)) `
        -Message "Stop-RecordedProcess must stop the recorded process."

    # PID reuse: same PID, different start time. Refusing here is the property that
    # keeps the launcher from killing an unrelated application.
    $reusedProcess = Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/c", "ping -n 60 127.0.0.1 > nul") -WindowStyle Hidden -PassThru
    $reusedRecordPath = Join-Path $RuntimeDirectory "reused-stub.json"
    Save-ProcessRecord -Process $reusedProcess -Path $reusedRecordPath
    $reusedRecord = Get-Content -LiteralPath $reusedRecordPath -Raw -Encoding utf8 | ConvertFrom-Json
    $reusedRecord.started_at_unix = [long]$reusedRecord.started_at_unix - 3600
    $reusedRecord | ConvertTo-Json | Set-Content -LiteralPath $reusedRecordPath -Encoding utf8
    Assert-LauncherTest `
        -Condition ($null -eq (Get-ProcessRecordMatch -RecordPath $reusedRecordPath -CommandPattern $cmdPattern)) `
        -Message "A record whose start time does not match the process must be rejected."
    Stop-RecordedProcess -DisplayName "reused stub" -RecordPath $reusedRecordPath -CommandPattern $cmdPattern
    Assert-LauncherTest `
        -Condition ($null -ne (Get-Process -Id $reusedProcess.Id -ErrorAction SilentlyContinue)) `
        -Message "A mismatched record must never stop the process it points at."
    Stop-StartedProcess -Process $reusedProcess
    Remove-Item -LiteralPath $reusedRecordPath -Force -ErrorAction SilentlyContinue

    Write-Host "Windows launcher tests passed."
}
finally {
    Send-TestDirectoryToRecycleBin -Path $RuntimeDirectory
}
