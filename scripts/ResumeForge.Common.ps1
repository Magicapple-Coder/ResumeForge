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
