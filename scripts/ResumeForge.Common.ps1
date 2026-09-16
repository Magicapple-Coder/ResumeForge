# ResumeForge launcher: process probes, health checks and shared lifecycle helpers.

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

function Get-ResumeForgeProcessPattern {
    param([ValidateSet("backend", "frontend")][string]$Service)

    # The command line that identifies our own process tree. It is recorded at
    # start and re-checked before anything is stopped or replaced, so PID reuse
    # can never hit an unrelated application.
    if ($Service -eq "backend") {
        return "uvicorn\s+app\.main:app"
    }
    return "npm\.cmd.*\brun\s+dev"
}

function Wait-ForCondition {
    param(
        [scriptblock]$Condition,
        [int]$TimeoutSeconds = 30,
        [AllowNull()]
        [System.Diagnostics.Process]$FailFastProcess = $null
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) {
            return $true
        }
        # A dead child will never become healthy. Report it immediately instead
        # of burning the whole timeout: a mis-quoted cmd exits in milliseconds,
        # and that failure should not look like a slow start.
        if ($null -ne $FailFastProcess) {
            try {
                if ($FailFastProcess.HasExited) {
                    return $false
                }
            }
            catch {
                # The handle can be gone; treat it as "not exited" and keep waiting.
            }
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

    # started_at_unix is the value used to detect PID reuse: it survives a JSON
    # round trip intact, whereas an ISO string comes back from ConvertFrom-Json as
    # a DateTime that has lost its UTC designator. started_at stays for humans.
    @{
        process_id      = $Process.Id
        started_at_unix = [DateTimeOffset]::new($Process.StartTime).ToUnixTimeSeconds()
        started_at      = $Process.StartTime.ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $Path -Encoding utf8
}

function Stop-StartedProcess {
    param(
        [AllowNull()]
        [System.Diagnostics.Process]$Process
    )

    if ($null -eq $Process) {
        return
    }

    # Stop-Process kills only the recorded process. For the frontend that is the
    # cmd.exe wrapper, so npm and the Vite/node child survive and keep the port
    # bound. taskkill /T walks the tree, matching what stop.cmd does.
    try {
        if ($Process.HasExited) {
            return
        }
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
    }
    catch {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}

function Get-LogTail {
    param(
        [string]$Path,
        [int]$LineCount = 12
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }
    try {
        # The backend runs with PYTHONUTF8=1, so its log is UTF-8. Reading it with
        # the locale codec (the Windows PowerShell default) turns every non-ASCII
        # message into mojibake exactly when it is needed most.
        $lines = @(Get-Content -LiteralPath $Path -Encoding utf8 -Tail $LineCount -ErrorAction Stop)
    }
    catch {
        return @()
    }
    return @($lines | Where-Object { $null -ne $_ -and $_.Trim().Length -gt 0 })
}

function Get-ProcessExitCodeText {
    param([AllowNull()][System.Diagnostics.Process]$Process)

    if ($null -eq $Process) {
        return "unknown"
    }
    try {
        # HasExited can already be true while ExitCode is still null, which used to
        # print "exited with code  before becoming healthy".
        $exitCode = $Process.ExitCode
        if ($null -ne $exitCode) {
            return "$exitCode"
        }
    }
    catch {
        # The handle can be gone by the time the message is built.
    }
    return "unknown"
}

function Format-ServiceStartFailure {
    param(
        [string]$DisplayName,
        [string]$Reason,
        [string]$LogPath
    )

    $message = "$DisplayName $Reason. See $LogPath"
    $tail = @(Get-LogTail -Path $LogPath)
    if ($tail.Count -eq 0) {
        return "$message (it is empty)."
    }
    # Print the tail here: the person double-clicking start.cmd is usually the one
    # who cannot act on a log path, and a bare "See runtime\backend.stderr.log" is
    # what made the first report of an incomplete package impossible to diagnose.
    return "$message. Last $($tail.Count) lines:`n" + ($tail -join "`n")
}

function Get-ProcessRecordField {
    param(
        [object]$Record,
        [string]$Name
    )

    # Read through PSObject instead of member access: a hand-edited or truncated
    # record then yields $null instead of an error under Set-StrictMode.
    $property = $Record.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Get-ProcessRecordMatch {
    param(
        [string]$RecordPath,
        [string]$CommandPattern
    )

    # Returns the recorded process when the record still describes it: same PID,
    # same start time and a matching command line. PID reuse and a stale record
    # both fail here, so nothing unrelated is ever stopped.
    if (-not (Test-Path -LiteralPath $RecordPath)) {
        return $null
    }
    try {
        $record = Get-Content -LiteralPath $RecordPath -Raw -Encoding utf8 | ConvertFrom-Json
        $processId = Get-ProcessRecordField -Record $record -Name "process_id"
        if ($null -eq $processId) {
            return $null
        }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            return $null
        }
        $cimProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction Stop
        if ($cimProcess.CommandLine -notmatch $CommandPattern) {
            return $null
        }
        $recordedAtUnix = Get-ProcessRecordField -Record $record -Name "started_at_unix"
        if ($null -ne $recordedAtUnix) {
            # Compared through Unix seconds: the record's ISO string loses its UTC
            # designator on the way back in, which used to make every comparison
            # miss by the local UTC offset.
            $recordedAt = [DateTimeOffset]::FromUnixTimeSeconds([long]$recordedAtUnix).UtcDateTime
            $startedAt = $process.StartTime.ToUniversalTime()
            if ([Math]::Abs(($startedAt - $recordedAt).TotalSeconds) -gt 2) {
                return $null
            }
        }
        else {
            # Records written before the Unix timestamp existed cannot be verified
            # by start time; the command line above still had to match.
            Write-Warning "The record at $RecordPath predates start-time verification; matching on the command line only."
        }
        return $process
    }
    catch {
        return $null
    }
}

function Stop-RecordedProcess {
    param(
        [string]$DisplayName,
        [string]$RecordPath,
        [string]$CommandPattern
    )

    if (-not (Test-Path -LiteralPath $RecordPath)) {
        return
    }

    $removeRecord = $false
    try {
        $record = Get-Content -LiteralPath $RecordPath -Raw -Encoding utf8 | ConvertFrom-Json
        $processId = Get-ProcessRecordField -Record $record -Name "process_id"
        $runningProcess = if ($null -ne $processId) {
            Get-Process -Id $processId -ErrorAction SilentlyContinue
        }
        else {
            $null
        }
        if ($null -eq $runningProcess) {
            Write-Host "Removed stale $DisplayName record."
            $removeRecord = $true
            return
        }

        if ($null -eq (Get-ProcessRecordMatch -RecordPath $RecordPath -CommandPattern $CommandPattern)) {
            Write-Warning "Did not stop ${DisplayName}: its record does not match the current process."
            return
        }

        & taskkill.exe /PID $processId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "taskkill returned exit code $LASTEXITCODE"
        }
        $removeRecord = $true
        Write-Host "Stopped $DisplayName."
    }
    catch {
        Write-Warning "Could not stop ${DisplayName}: $($_.Exception.Message)"
    }
    finally {
        if ($removeRecord) {
            Remove-Item -LiteralPath $RecordPath -Force -ErrorAction SilentlyContinue
        }
    }
}
