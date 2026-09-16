[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDirectory = Join-Path $ProjectRoot "runtime"

# The process-record helpers live in ResumeForge.Common.ps1 with the rest of the
# launcher helpers so the start path can reuse them: a leftover process that still
# holds its port is stopped through the same PID, start-time and command-line
# checks, never by name.
. (Join-Path $PSScriptRoot "ResumeForge.Common.ps1")

Stop-RecordedProcess `
    -DisplayName "frontend" `
    -RecordPath (Join-Path $RuntimeDirectory "frontend.json") `
    -CommandPattern (Get-ResumeForgeProcessPattern -Service "frontend")
Stop-RecordedProcess `
    -DisplayName "backend" `
    -RecordPath (Join-Path $RuntimeDirectory "backend.json") `
    -CommandPattern (Get-ResumeForgeProcessPattern -Service "backend")
