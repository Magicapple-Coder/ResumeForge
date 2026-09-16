[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Packages the current HEAD for real and inspects the result. The point of this
# test is the failure a user reported once: a hand-made zip shipped without
# backend\app\data, so the backend died at import time on a fresh machine.

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BuildScriptPath = Join-Path $ProjectRoot "scripts\Build-Release.ps1"
$PreflightPath = Join-Path $ProjectRoot "backend\app\preflight.py"
$ConfigPath = Join-Path $ProjectRoot "backend\app\config.py"
$RuntimeDirectory = Join-Path ([IO.Path]::GetTempPath()) ("resumeforge-release-test-" + [Guid]::NewGuid().ToString("N"))

# The maintainer's database and configuration, local runtimes and caches must
# never be packaged. backend/.env.example is the documented exception: it is
# tracked on purpose.
$ForbiddenInArchive = @(
    "^backend/data/",
    "^backend/\.venv/",
    "^frontend/node_modules/",
    "^runtime/",
    "(^|/)\.env(\.|$)",
    "(^|/)__pycache__/"
)
$AllowedInArchive = @("backend/.env.example")

function Assert-ReleaseTest {
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
        Write-Warning "Could not move release test data to the recycle bin; leaving it in place: $($_.Exception.Message)"
    }
}

function Read-ZipEntryText {
    param([System.IO.Compression.ZipArchiveEntry]$Entry)

    $stream = $Entry.Open()
    try {
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
        try {
            return $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Get-ScriptArrayValues {
    # Reads an array-valued variable out of a script without running it.
    param(
        [System.Management.Automation.Language.ScriptBlockAst]$Ast,
        [string]$Name
    )

    $assignment = $Ast.FindAll(
        {
            param($node)
            return $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
                $node.Left.Extent.Text -eq $Name
        },
        $true
    ) | Select-Object -First 1
    if ($null -eq $assignment) {
        return @()
    }
    return @($assignment.Right.FindAll(
            { param($node) $node -is [System.Management.Automation.Language.StringConstantExpressionAst] },
            $true
        ) | ForEach-Object { $_.Value })
}

function Read-TextFileAsUtf8 {
    param([string]$Path)

    # Windows PowerShell 5.1 decodes text files with the locale codec, which
    # mangles the Chinese comments in these sources.
    return [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($Path))
}

try {
    New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null

    $tokens = $null
    $parseErrors = $null
    $buildAst = [System.Management.Automation.Language.Parser]::ParseFile(
        $BuildScriptPath,
        [ref]$tokens,
        [ref]$parseErrors
    )
    Assert-ReleaseTest `
        -Condition ($parseErrors.Count -eq 0) `
        -Message "Build-Release.ps1 has PowerShell syntax errors."

    # The script is read by Windows PowerShell 5.1, which decodes a BOM-less file
    # with the locale codec (cp936 on Chinese Windows). Chinese text inside would
    # come out as mojibake, or break parsing. Keep it ASCII.
    $nonAsciiBytes = @([System.IO.File]::ReadAllBytes($BuildScriptPath) | Where-Object { $_ -gt 0x7F }).Count
    Assert-ReleaseTest `
        -Condition ($nonAsciiBytes -eq 0) `
        -Message "Build-Release.ps1 must stay pure ASCII (found $nonAsciiBytes non-ASCII bytes)."

    # --- the packaging run itself ---
    # A thrown error inside the build script propagates and fails this test; the
    # presence of the archive below is the positive signal.
    & $BuildScriptPath -OutputDirectory $RuntimeDirectory

    $archive = Get-ChildItem -LiteralPath $RuntimeDirectory -Filter "ResumeForge-*.zip" -File |
        Select-Object -First 1
    Assert-ReleaseTest -Condition ($null -ne $archive) -Message "The build script produced no archive."

    $configContent = Read-TextFileAsUtf8 -Path $ConfigPath
    $version = [regex]::Match($configContent, 'app_version:\s*str\s*=\s*"([^"]+)"').Groups[1].Value
    Assert-ReleaseTest -Condition (-not [string]::IsNullOrWhiteSpace($version)) -Message "Could not read app_version."
    Assert-ReleaseTest `
        -Condition ($archive.Name -eq "ResumeForge-$version.zip") `
        -Message "The archive must be named after the packaged version (got $($archive.Name))."

    $prefix = "ResumeForge-$version/"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($archive.FullName)
    try {
        $fileEntries = @($zip.Entries | Where-Object { $_.Name -ne "" })
        $entries = @($fileEntries | ForEach-Object { $_.FullName })

        Assert-ReleaseTest `
            -Condition (@($entries | Where-Object { -not $_.StartsWith($prefix) }).Count -eq 0) `
            -Message "Every archive entry must live under $prefix so extraction creates one folder."
        $relativePaths = @($entries | ForEach-Object { $_.Substring($prefix.Length) })

        # Exactly the tracked tree: this is what a hand-made zip got wrong.
        $trackedFiles = @(& git -C $ProjectRoot ls-tree -r --name-only HEAD)
        Assert-ReleaseTest -Condition ($trackedFiles.Count -gt 0) -Message "git ls-tree returned nothing."
        Assert-ReleaseTest `
            -Condition ($relativePaths.Count -eq $trackedFiles.Count) `
            -Message "The archive must hold exactly the tracked files: $($relativePaths.Count) in the zip vs $($trackedFiles.Count) in git."
        $trackedSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($trackedFile in $trackedFiles) {
            [void]$trackedSet.Add($trackedFile)
        }
        $unexpected = @($relativePaths | Where-Object { -not $trackedSet.Contains($_) })
        Assert-ReleaseTest `
            -Condition ($unexpected.Count -eq 0) `
            -Message "The archive contains untracked files: $($unexpected -join ', ')"

        foreach ($required in @(
                "backend/app/data/skills.json",
                "backend/app/preflight.py",
                "backend/app/prompts/resume_generate_user.md",
                "backend/migrations/versions/0005_chat_assistant.py"
            )) {
            Assert-ReleaseTest `
                -Condition ($relativePaths -contains $required) `
                -Message "The archive is missing $required."
        }

        foreach ($forbidden in $ForbiddenInArchive) {
            $leaked = @($relativePaths | Where-Object { $AllowedInArchive -notcontains $_ -and $_ -match $forbidden })
            Assert-ReleaseTest `
                -Condition ($leaked.Count -eq 0) `
                -Message "Personal data or caches leaked into the archive: $($leaked -join ', ')"
        }

        # .gitattributes asks for CRLF in .cmd; a zip built with LF-only batch files
        # can misbehave in cmd.exe, and that is invisible until a user runs it.
        $startCmdEntry = $fileEntries | Where-Object { $_.FullName -eq "${prefix}start.cmd" } | Select-Object -First 1
        Assert-ReleaseTest -Condition ($null -ne $startCmdEntry) -Message "start.cmd is missing from the archive."
        $startCmdText = Read-ZipEntryText -Entry $startCmdEntry
        Assert-ReleaseTest `
            -Condition (-not ($startCmdText -match "(?<!\r)\n")) `
            -Message "start.cmd inside the archive must use CRLF line endings."
    }
    finally {
        $zip.Dispose()
    }

    # --- the packaging checklist and the in-app check must agree ---
    $buildRequiredFiles = Get-ScriptArrayValues -Ast $buildAst -Name '$RequiredFiles'
    Assert-ReleaseTest `
        -Condition ($buildRequiredFiles.Count -ge 10) `
        -Message "Could not read the required-file list from Build-Release.ps1."
    $preflightContent = Read-TextFileAsUtf8 -Path $PreflightPath
    foreach ($requiredPath in $buildRequiredFiles) {
        if (-not $requiredPath.StartsWith("backend/")) {
            continue
        }
        $backendRelative = $requiredPath.Substring("backend/".Length)
        Assert-ReleaseTest `
            -Condition ($preflightContent.Contains('"' + $backendRelative + '"')) `
            -Message "backend/app/preflight.py does not check '$backendRelative', but the packager requires it."
    }

    Write-Host "Release packaging tests passed."
}
finally {
    Send-TestDirectoryToRecycleBin -Path $RuntimeDirectory
}
