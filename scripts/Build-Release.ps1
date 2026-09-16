<#
.SYNOPSIS
Builds the distributable ResumeForge zip from a git ref, then verifies it.

.DESCRIPTION
A release archive has to contain every tracked file and nothing else. A hand-made
zip once shipped without backend\app\data, so the backend died at import time with
FileNotFoundError and the user only saw "Backend exited ... See
runtime\backend.stderr.log". git archive cannot make that mistake: it copies the
tracked tree of the ref, applies the .gitattributes line endings, and leaves
everything .gitignore excludes behind (the personal database in backend\data,
backend\.env, runtime\, node_modules, caches).

After writing the archive this script re-opens it and checks both sides: the paths
a fresh machine cannot start without, and the paths that must never leak into a
release. An archive that fails verification is deleted instead of published.

.PARAMETER Ref
Git ref to package: a tag, branch or commit. Defaults to HEAD.

.PARAMETER OutputDirectory
Target directory for ResumeForge-<version>.zip. Defaults to <project>\dist.

.EXAMPLE
.\scripts\Build-Release.ps1 -Ref v0.6.0
#>
[CmdletBinding()]
param(
    [string]$Ref = "HEAD",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $ProjectRoot "dist"
}

# Paths a release cannot start without. backend\app\preflight.py checks the same
# ground for the running app; Test-Build-Release.ps1 asserts the two lists agree,
# so packaging stays verifiable on a machine that has no Python environment yet.
$RequiredFiles = @(
    "backend/app/main.py",
    "backend/app/preflight.py",
    "backend/app/data/skills.json",
    "backend/app/prompts/assistant_system.md",
    "backend/app/prompts/assistant_welcome.md",
    "backend/app/prompts/image_extraction_addendum.md",
    "backend/app/prompts/job_analysis.md",
    "backend/app/prompts/job_text_extract.md",
    "backend/app/prompts/profile_text_extract.md",
    "backend/app/prompts/resume_fix_json.md",
    "backend/app/prompts/resume_generate_system.md",
    "backend/app/prompts/resume_generate_user.md",
    "backend/app/prompts/resume_quality_retry.md",
    "backend/app/prompts/resume_suggestions.md",
    "backend/app/templates/resume.html.j2",
    "backend/app/templates/resume_modern.html.j2",
    "backend/app/templates/resume_compact.html.j2",
    "backend/app/templates/_resume_sections.j2",
    "backend/app/templates/_resume_fit_script.j2",
    "backend/requirements.txt",
    "backend/alembic.ini",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "scripts/Start-ResumeForge.ps1",
    "scripts/Stop-ResumeForge.ps1",
    "start.cmd",
    "stop.cmd"
)

# Must contain at least one file each. Every prompt and the skill dictionary are
# named individually above; these cover directories whose size is not fixed.
$RequiredPrefixes = @(
    "backend/app/data/",
    "backend/migrations/versions/",
    "frontend/src/"
)

# Must never appear in a release: the maintainer's database and configuration,
# local runtimes, build output and caches. Matched as regexes against the path
# inside the archive.
$ForbiddenPatterns = @(
    "^backend/data/",
    "^backend/\.venv/",
    "^frontend/node_modules/",
    "^frontend/dist/",
    "^runtime/",
    "^\.git/",
    "(^|/)\.env(\.|$)",
    "(^|/)__pycache__/",
    "(^|/)\.pytest_cache/"
)

# Tracked paths that only look forbidden: the example configuration is meant to
# ship, and .gitignore keeps the real .env out with a "!.env.example" exception.
# Matches in any directory (backend/ and frontend/ both have one).
$AllowedPathPattern = "(^|/)\.env\.example$"

function Invoke-GitCapture {
    param([string[]]$Arguments)

    # Native stderr output becomes a terminating error under
    # ErrorActionPreference = "Stop", and several probes below are expected to fail
    # (git describe on a commit that carries no tag). The exit code is the signal.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        return @(& git -C $ProjectRoot @Arguments 2>$null)
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-RefAppVersion {
    # Read the version from the ref being packaged, not from the working tree: a
    # checkout of HEAD packaging tag v0.5.0 would otherwise name the archive with
    # the wrong version.
    # No $LASTEXITCODE check here: it belongs to the scope of the call, and the
    # helper runs the native command in its own. Empty output means the ref does
    # not carry the file.
    $lines = @(Invoke-GitCapture -Arguments @("show", "${Ref}:backend/app/config.py"))
    if ($lines.Count -eq 0) {
        throw "Ref '$Ref' does not contain backend/app/config.py."
    }
    $content = $lines -join "`n"
    $match = [regex]::Match($content, 'app_version:\s*str\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Could not read app_version from backend/app/config.py at '$Ref'."
    }
    return $match.Groups[1].Value
}

function Get-ArchiveEntryList {
    param([string]$ArchivePath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        # Directory entries carry an empty Name; only files matter here.
        return @($archive.Entries | Where-Object { $_.Name -ne "" } | ForEach-Object { $_.FullName })
    }
    finally {
        $archive.Dispose()
    }
}

if ($null -eq (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git was not found on PATH. This script packages a git ref; install Git, or hand out an existing release zip."
}

$version = Get-RefAppVersion
$headCommit = @(Invoke-GitCapture -Arguments @("rev-parse", "--short", $Ref))[0]
# Empty when the ref carries no tag, which is the normal case while developing.
$tag = @(Invoke-GitCapture -Arguments @("describe", "--tags", "--exact-match", $Ref))
$tag = if ($tag.Count -gt 0) { $tag[0] } else { "" }
$pendingChanges = @(Invoke-GitCapture -Arguments @("status", "--porcelain"))

$archiveName = "ResumeForge-$version.zip"
$archivePath = Join-Path $OutputDirectory $archiveName
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}

$prefix = "ResumeForge-$version/"
& git -C $ProjectRoot archive --format=zip "--prefix=$prefix" -o $archivePath $Ref
if ($LASTEXITCODE -ne 0) {
    throw "git archive failed for ref '$Ref' (exit $LASTEXITCODE)."
}

$entries = @(Get-ArchiveEntryList -ArchivePath $archivePath)
$relativePaths = @(
    $entries | ForEach-Object { if ($_.StartsWith($prefix, [StringComparison]::Ordinal)) { $_.Substring($prefix.Length) } else { $_ } }
)
$entrySet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($relativePath in $relativePaths) {
    [void]$entrySet.Add($relativePath)
}

$problems = @()
foreach ($required in $RequiredFiles) {
    if (-not $entrySet.Contains($required)) {
        $problems += "missing file: $required"
    }
}
foreach ($requiredPrefix in $RequiredPrefixes) {
    # Not $matches: that is the automatic variable -match writes into, and
    # clobbering it makes later -match tests in this scope read stale data.
    $matchedPaths = @($relativePaths | Where-Object { $_.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase) })
    if ($matchedPaths.Count -eq 0) {
        $problems += "missing directory contents: $requiredPrefix"
    }
}
foreach ($pattern in $ForbiddenPatterns) {
    $leaked = @($relativePaths | Where-Object { $_ -notmatch $AllowedPathPattern -and $_ -match $pattern })
    if ($leaked.Count -gt 0) {
        $problems += "must not be packaged: $($leaked[0])"
    }
}
if ($problems.Count -gt 0) {
    Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
    $report = $problems -join "`n  "
    throw ("Archive verification failed, so it was deleted:`n  " + $report)
}

$sizeInMegabytes = [math]::Round((Get-Item -LiteralPath $archivePath).Length / 1MB, 2)
Write-Host ""
Write-Host "Archive  : $archivePath"
Write-Host "Ref      : $Ref ($headCommit)"
if ($tag) {
    Write-Host "Tag      : $tag"
}
Write-Host "Contents : $($entries.Count) files, $sizeInMegabytes MB"
Write-Host "Verified : $($RequiredFiles.Count) required files present, $($RequiredPrefixes.Count) required directories non-empty, $($ForbiddenPatterns.Count) forbidden patterns absent"
if ($pendingChanges.Count -gt 0 -and $Ref -eq "HEAD") {
    Write-Warning "The working tree has uncommitted changes. The archive contains the committed state of HEAD only; commit first if you meant to ship them."
}
Write-Host ""
Write-Host "Next: attach this file to the GitHub release for v$version, or hand it out as-is."
