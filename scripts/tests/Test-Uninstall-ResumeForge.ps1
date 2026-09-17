<#
Tests for scripts\Uninstall-ResumeForge.ps1.

The uninstaller deletes things on purpose, so it is never pointed at the real
checkout here. Each case builds a throwaway folder that *looks* like a
ResumeForge checkout (backend\app + frontend\package.json), copies the real
script into it, and runs that copy. This also proves the "only operate inside a
checkout" guard, because the copy resolves its project root from its own
location.

Run: powershell -NoProfile -File scripts\tests\Test-Uninstall-ResumeForge.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$UninstallerSource = Join-Path $ProjectRoot "scripts\Uninstall-ResumeForge.ps1"
$FixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ("resumeforge-uninstall-test-" + [Guid]::NewGuid().ToString("N"))

function Assert-UninstallTest {
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
    } catch {
        Write-Warning "Could not send $Path to the Recycle Bin: $($_.Exception.Message)"
    }
}

function New-CheckoutFixture {
    param([string]$Name)

    $root = Join-Path $FixtureRoot $Name
    # The two markers the uninstaller checks before it will touch anything.
    New-Item -ItemType Directory -Force -Path (Join-Path $root "backend\app") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $root "frontend") | Out-Null
    Set-Content -LiteralPath (Join-Path $root "frontend\package.json") -Value "{}" -Encoding utf8

    New-Item -ItemType Directory -Force -Path (Join-Path $root "scripts") | Out-Null
    Copy-Item -LiteralPath $UninstallerSource -Destination (Join-Path $root "scripts")

    # Everything the launcher creates.
    foreach ($relative in @("backend\.venv\Scripts", "frontend\node_modules\antd", "frontend\dist", "runtime")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $root $relative) | Out-Null
    }
    Set-Content -LiteralPath (Join-Path $root "backend\.venv\Scripts\python.exe") -Value "stub"
    Set-Content -LiteralPath (Join-Path $root "frontend\node_modules\antd\index.js") -Value "stub"

    # User data.
    New-Item -ItemType Directory -Force -Path (Join-Path $root "backend\data") | Out-Null
    Set-Content -LiteralPath (Join-Path $root "backend\data\resume_forge.db") -Value "stub"
    Set-Content -LiteralPath (Join-Path $root "backend\.env") -Value "KEY=value"

    return $root
}

function Invoke-Uninstaller {
    param(
        [string]$Root,
        [string[]]$Arguments = @()
    )

    $script = Join-Path $Root "scripts\Uninstall-ResumeForge.ps1"
    # No -ExecutionPolicy Bypass here: the fixtures are local files, and the
    # default RemoteSigned policy already allows those. Adding the flag would
    # make the test pass on machines where the real script could not run.
    $process = Start-Process -FilePath "powershell.exe" `
        -ArgumentList (@("-NoProfile", "-File", $script) + $Arguments) `
        -Wait -PassThru -NoNewWindow
    return $process.ExitCode
}

try {
    Assert-UninstallTest -Condition (Test-Path -LiteralPath $UninstallerSource) `
        -Message "scripts\Uninstall-ResumeForge.ps1 is missing."

    # --- Default run: dependencies go, data and source stay ------------------
    $root = New-CheckoutFixture -Name "keep-data"
    Assert-UninstallTest -Condition ((Invoke-Uninstaller -Root $root -Arguments @("-Yes")) -eq 0) `
        -Message "A normal uninstall should exit 0."

    foreach ($relative in @("backend\.venv", "frontend\node_modules", "frontend\dist", "runtime")) {
        Assert-UninstallTest -Condition (-not (Test-Path -LiteralPath (Join-Path $root $relative))) `
            -Message "Uninstall should remove $relative."
    }
    # The whole point of the default: your database and API keys survive.
    Assert-UninstallTest -Condition (Test-Path -LiteralPath (Join-Path $root "backend\data\resume_forge.db")) `
        -Message "Uninstall must keep backend\data unless -Purge is given."
    Assert-UninstallTest -Condition (Test-Path -LiteralPath (Join-Path $root "backend\.env")) `
        -Message "Uninstall must keep backend\.env unless -Purge is given."
    # It is an uninstaller, not a "delete my repository" button.
    Assert-UninstallTest -Condition (Test-Path -LiteralPath (Join-Path $root "backend\app")) `
        -Message "Uninstall must never delete the source code."
    Assert-UninstallTest -Condition (Test-Path -LiteralPath (Join-Path $root "frontend\package.json")) `
        -Message "Uninstall must never delete the source code."

    # --- -Purge: data goes too ----------------------------------------------
    $purgeRoot = New-CheckoutFixture -Name "purge"
    Assert-UninstallTest -Condition ((Invoke-Uninstaller -Root $purgeRoot -Arguments @("-Purge", "-Yes")) -eq 0) `
        -Message "A purge uninstall should exit 0."

    Assert-UninstallTest -Condition (-not (Test-Path -LiteralPath (Join-Path $purgeRoot "backend\data"))) `
        -Message "-Purge should remove backend\data."
    Assert-UninstallTest -Condition (-not (Test-Path -LiteralPath (Join-Path $purgeRoot "backend\.env"))) `
        -Message "-Purge should remove backend\.env."
    Assert-UninstallTest -Condition (Test-Path -LiteralPath (Join-Path $purgeRoot "backend\app")) `
        -Message "Even -Purge must not delete the source code."

    # --- Refuses to run outside a checkout ----------------------------------
    # This is what keeps a stray copy of the script from deleting a random folder.
    $strangerRoot = Join-Path $FixtureRoot "not-a-checkout"
    New-Item -ItemType Directory -Force -Path (Join-Path $strangerRoot "scripts") | Out-Null
    Copy-Item -LiteralPath $UninstallerSource -Destination (Join-Path $strangerRoot "scripts")
    # Put a real target there: if the guard ever stopped working, this is the
    # folder the script would walk into.
    New-Item -ItemType Directory -Force -Path (Join-Path $strangerRoot "frontend\node_modules\to-keep") | Out-Null

    $strangerExit = Invoke-Uninstaller -Root $strangerRoot -Arguments @("-Yes")
    Assert-UninstallTest -Condition ($strangerExit -ne 0) `
        -Message "Running in a folder that is not a checkout must fail loudly."
    Assert-UninstallTest -Condition (Test-Path -LiteralPath (Join-Path $strangerRoot "frontend\node_modules\to-keep")) `
        -Message "The guard must run before anything is deleted."

    # --- Prompt is skipped by -Yes, and cancelling deletes nothing -----------
    # Without -Yes the script reads from stdin; send a non-"YES" answer and make
    # sure nothing disappears. This is the safety net a user hits by mistake.
    $cancelRoot = New-CheckoutFixture -Name "cancel"
    $cancelScript = Join-Path $cancelRoot "scripts\Uninstall-ResumeForge.ps1"
    "no`n" | & powershell.exe -NoProfile -File $cancelScript | Out-Null
    Assert-UninstallTest -Condition (Test-Path -LiteralPath (Join-Path $cancelRoot "backend\.venv")) `
        -Message "Answering anything but YES must leave the folder untouched."
    Assert-UninstallTest -Condition (Test-Path -LiteralPath (Join-Path $cancelRoot "backend\data")) `
        -Message "Cancelling must leave the data untouched."

    Write-Host "Uninstaller tests passed."
}
finally {
    Send-TestDirectoryToRecycleBin -Path $FixtureRoot
}
