[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDirectory = Join-Path $ProjectRoot "runtime"

function Stop-RecordedProcess {
    param(
        [string]$Name,
        [string]$CommandPattern
    )

    $recordPath = Join-Path $RuntimeDirectory "$Name.json"
    if (-not (Test-Path -LiteralPath $recordPath)) {
        return
    }

    $removeRecord = $false
    try {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $runningProcess = Get-Process -Id $record.process_id -ErrorAction SilentlyContinue
        if ($null -eq $runningProcess) {
            Write-Host "Removed stale $Name record."
            $removeRecord = $true
            return
        }

        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.process_id)" -ErrorAction Stop

        # PID reuse is possible. Require a matching start time and command before
        # terminating a process tree, so this script cannot stop an unrelated app.
        # The start time is compared through Unix seconds: parsing the record's ISO
        # string loses its UTC designator, which made every comparison off by the
        # local UTC offset and stopped this script from ever matching a live app.
        $startTimeMatches = $true
        if ($null -ne $record.started_at_unix) {
            $recordedAt = [DateTimeOffset]::FromUnixTimeSeconds([long]$record.started_at_unix).UtcDateTime
            $startedAt = $runningProcess.StartTime.ToUniversalTime()
            $startTimeMatches = [Math]::Abs(($startedAt - $recordedAt).TotalSeconds) -le 2
        }
        else {
            # Records written before the Unix timestamp was introduced cannot be
            # verified; the command line below still has to match.
            Write-Warning "The $Name record predates start-time verification; matching on the command line only."
        }

        if (-not $startTimeMatches -or $process.CommandLine -notmatch $CommandPattern) {
            Write-Warning "Did not stop ${Name}: its record does not match the current process."
            return
        }

        & taskkill.exe /PID $record.process_id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "taskkill returned exit code $LASTEXITCODE"
        }
        $removeRecord = $true
        Write-Host "Stopped $Name."
    }
    catch {
        Write-Warning "Could not stop ${Name}: $($_.Exception.Message)"
    }
    finally {
        if ($removeRecord) {
            Remove-Item -LiteralPath $recordPath -Force -ErrorAction SilentlyContinue
        }
    }
}

Stop-RecordedProcess -Name "frontend" -CommandPattern "npm\.cmd.*\brun\s+dev"
Stop-RecordedProcess -Name "backend" -CommandPattern "uvicorn\s+app\.main:app"
