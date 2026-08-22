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

function Assert-LauncherTest {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
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
        '$NodeBootstrapArm64Sha256 = "8502f4a50b458d4cc38ed8f2001556c2cd239d464920f74017926ccb1e1c157f"'
    )) {
    Assert-LauncherTest `
        -Condition $launcherContent.Contains($requiredSetting) `
        -Message "The launcher bootstrap setting is missing or unexpected: $requiredSetting"
}

# Load function definitions without executing the launcher's service startup.
$functionDefinitions = $launcherAst.FindAll(
    {
        param($node)
        return $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    },
    $true
)
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

    Write-Host "Windows launcher tests passed."
}
finally {
    Remove-Item -LiteralPath $RuntimeDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
