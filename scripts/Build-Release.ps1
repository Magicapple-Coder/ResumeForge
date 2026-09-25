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

.PARAMETER Platform
Which launcher set the archive should carry. "all" (default) keeps everything and
is the archive attached to the GitHub release. "windows" / "macos" produce the two
archives the website offers for direct download: each keeps only its own launcher
set, so the user who just downloaded one never has to guess between start.cmd and
start.command. The other platform's launchers are removed AFTER git archive (which
always emits the whole tree), and verification runs per platform, so a pruning bug
fails loudly instead of shipping a half archive.

.EXAMPLE
.\scripts\Build-Release.ps1 -Ref v0.6.0
.EXAMPLE
.\scripts\Build-Release.ps1 -Ref v0.12.0 -Platform macos
#>
[CmdletBinding()]
param(
    [string]$Ref = "HEAD",
    [string]$OutputDirectory = "",
    [ValidateSet("all", "windows", "macos")]
    [string]$Platform = "all"
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
# Every path here is one backend/app/preflight.py refuses to start without. The
# list used to lag behind preflight (22 entries were missing, so the launcher and
# release-packaging test failed on every run while the archive was in fact fine);
# test Test-Build-Release.ps1 now compares the two lists in one direction, so a
# new resource added to preflight without being added here turns that test red.
$RequiredFiles = @(
    "backend/app/main.py",
    "backend/app/preflight.py",
    "backend/app/data/skills.json",
    "backend/app/data/ats_keywords.json",
    "backend/app/prompts/application_status.md",
    "backend/app/prompts/apply_greeting.md",
    "backend/app/prompts/assistant_system.md",
    "backend/app/prompts/assistant_welcome.md",
    "backend/app/prompts/claim_draft.md",
    "backend/app/prompts/drill_common.md",
    "backend/app/prompts/drill_contract.md",
    "backend/app/prompts/drill_evaluate.md",
    "backend/app/prompts/drill_review.md",
    "backend/app/prompts/image_extraction_addendum.md",
    "backend/app/prompts/interview_analysis.md",
    "backend/app/prompts/interview_answer.md",
    "backend/app/prompts/interview_optimize_resume.md",
    "backend/app/prompts/interview_questions.md",
    "backend/app/prompts/interview_report.md",
    "backend/app/prompts/interview_system.md",
    "backend/app/prompts/job_analysis.md",
    "backend/app/prompts/job_match.md",
    "backend/app/prompts/job_multi_extract.md",
    "backend/app/prompts/job_text_extract.md",
    "backend/app/prompts/profile_text_extract.md",
    "backend/app/prompts/resume_fix_json.md",
    "backend/app/prompts/resume_generate_system.md",
    "backend/app/prompts/resume_generate_user.md",
    "backend/app/prompts/resume_phrases.md",
    "backend/app/prompts/resume_polish.md",
    "backend/app/prompts/resume_quality_retry.md",
    "backend/app/prompts/resume_rewrite_field.md",
    "backend/app/prompts/resume_template_import.md",
    "backend/app/prompts/resume_risk.md",
    "backend/app/prompts/resume_star.md",
    "backend/app/prompts/resume_suggestions.md",
    "backend/app/prompts/resume_translate.md",
    "backend/app/services/feature_catalog.py",
    "backend/app/templates/resume.html.j2",
    "backend/app/templates/resume_modern.html.j2",
    "backend/app/templates/resume_compact.html.j2",
    "backend/app/templates/_resume_blocks.j2",
    "backend/app/templates/_resume_sections.j2",
    "backend/app/templates/_resume_fit_script.j2",
    "backend/requirements.txt",
    "backend/alembic.ini",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html"
)

# Per-platform launcher sets. The "all" archive carries both (that is the one the
# GitHub release attaches); the website's two download buttons hand out the pruned
# ones, so nobody has to guess which file to double-click.
$PlatformLaunchers = @{
    windows = @(
        "start.cmd",
        "stop.cmd",
        "update.cmd",
        "uninstall.cmd",
        "scripts/Start-ResumeForge.ps1",
        "scripts/Stop-ResumeForge.ps1",
        "scripts/Update-ResumeForge.ps1",
        "scripts/Uninstall-ResumeForge.ps1"
    )
    macos = @(
        "start.command",
        "stop.command",
        "update.command",
        "scripts/macos/start.sh",
        "scripts/macos/stop.sh",
        "scripts/macos/update.sh",
        "scripts/macos/lib/common.sh",
        "scripts/macos/lib/python.sh",
        "scripts/macos/lib/node.sh",
        # The guard test travels with the macos launcher set: the windows archive
        # prunes scripts/macos together with this file, so it cannot live in the
        # common required list (the windows verification would then demand a file
        # that the windows archive deliberately does not carry).
        "scripts/tests/test-macos-launcher.sh"
    )
}

# What the OTHER platform's launcher set looks like, per platform:
#   $PrunePathspecs -- paths handed to `git archive ... :(exclude)<path>` so the
#   pruned archive simply never contains them (line endings and executable bits
#   therefore stay exactly as the "all" archive produces them);
#   $PrunePatterns  -- the same set as regexes, re-checked afterwards against the
#   finished archive so a pathspec typo fails verification instead of shipping.
# Kept next to the launcher lists on purpose: adding a launcher above without
# teaching the pruner about it means the pruned archive still carries the other
# platform's launcher, which the per-platform verification turns into a hard error.
$PrunePathspecs = @{
    windows = @(
        ":(exclude)start.command",
        ":(exclude)stop.command",
        ":(exclude)update.command",
        ":(exclude)scripts/macos",
        ":(exclude)scripts/tests/test-macos-launcher.sh"
    )
    macos = @(
        ":(exclude)start.cmd",
        ":(exclude)stop.cmd",
        ":(exclude)update.cmd",
        ":(exclude)uninstall.cmd",
        ":(exclude,glob)scripts/*.ps1",
        ":(exclude,glob)scripts/tests/*.ps1"
    )
}

$PrunePatterns = @{
    windows = @(
        "^start\.command$",
        "^stop\.command$",
        "^update\.command$",
        "^scripts/macos/"
    )
    macos = @(
        "^start\.cmd$",
        "^stop\.cmd$",
        "^update\.cmd$",
        "^uninstall\.cmd$",
        "^scripts/[^/]+\.ps1$",
        "^scripts/tests/.*\.ps1$"
    )
}

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
#
# frontend/.env.demo is the second exception, for a different reason: it is not a
# user configuration at all but the build-mode switch for the online demo bundle
# (`vite build --mode demo` reads it, and it only holds VITE_DEMO_MODE=1). It has
# to be tracked so the demo build is reproducible from a clean clone, and
# .gitignore re-includes it for exactly that reason. Shipping it to end users
# would be pointless but harmless; excluding it is the tidier contract, since
# anything matching `\.env` in a release archive otherwise signals a leak. The
# pattern is anchored so it cannot accidentally exempt `frontend/.env.demo.local`
# (which is gitignored, but a future `!.env.demo.*` exception would be a real
# leak: that file carries local parent-origin allowlist entries).
$AllowedPathPattern = "(^|/)\.env\.example$|^frontend/\.env\.demo$"

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

# Required files for THIS archive: the common list plus the launcher set it carries.
#
# PowerShell variables are CASE-INSENSITIVE: $activePrunePatterns and the
# $PrunePatterns table above would be the *same* variable if the only difference
# were letter case (measured: the array assignment silently replaced the table,
# and the table lookup then failed as a baffling "cannot convert String to
# Int32"). That is why the per-platform actives are named with the "active"
# prefix instead of a different casing of the tables.
$platformRequired = @($RequiredFiles)
$activePrunePathspecs = @()
$activePrunePatterns = @()
if ($Platform -eq "all") {
    $platformRequired = @($RequiredFiles) + $PlatformLaunchers["windows"] + $PlatformLaunchers["macos"]
}
else {
    $platformRequired = @($RequiredFiles) + $PlatformLaunchers[$Platform]
    $activePrunePathspecs = @($PrunePathspecs[$Platform])
    $activePrunePatterns = @($PrunePatterns[$Platform])
}

$suffix = if ($Platform -eq "all") { "" } else { "-$Platform" }
$archiveName = "ResumeForge-$version$suffix.zip"
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

if ($activePrunePathspecs.Count -gt 0) {
    # git archive always emits the whole tree and cannot exclude paths by itself,
    # but its pathspec machinery can: pass :(exclude)<path> after the ref. Doing
    # it this way (instead of rewriting the zip by hand) keeps line endings from
    # .gitattributes and the executable bits from the tree exactly as the "all"
    # archive produces them -- those are the two things a Mac user cannot fix.
    # The table already carries the :(exclude) magic (glob where needed), so the
    # tokens are passed through verbatim.
    $pathArguments = @($activePrunePathspecs)
    Remove-Item -LiteralPath $archivePath -Force
    & git -C $ProjectRoot archive --format=zip "--prefix=$prefix" -o $archivePath $Ref -- $pathArguments
    if ($LASTEXITCODE -ne 0) {
        throw "git archive (pruned) failed for ref '$Ref' (exit $LASTEXITCODE)."
    }
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
foreach ($required in $platformRequired) {
    if (-not $entrySet.Contains($required)) {
        $problems += "missing file: $required"
    }
}
foreach ($pattern in $activePrunePatterns) {
    # Pruned means GONE: a single-platform archive that still carries the other
    # platform's launcher hands the user the exact confusion this option exists
    # to remove ("picked macos, got start.cmd").
    $leaked = @($relativePaths | Where-Object { $_ -match $pattern })
    if ($leaked.Count -gt 0) {
        $problems += "platform $Platform must not carry: $($leaked[0])"
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

# SHA256 sidecar next to the archive. Two reasons it matters here:
#   1. Users who hit an antivirus / SmartScreen prompt should be able to verify that the
#      file they downloaded is byte-identical to what was built here.
#   2. The package ships no .exe/.msi at all (only source, scripts and docs), so the
#      checksum is the concrete thing a cautious user can actually check.
# Written in the conventional "<hash>  <filename>" format so `sha256sum -c` works.
$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath = "$archivePath.sha256"
$checksumLine = "$hash  $([System.IO.Path]::GetFileName($archivePath))"
Set-Content -LiteralPath $checksumPath -Value $checksumLine -Encoding ASCII

Write-Host ""
Write-Host "Archive  : $archivePath"
Write-Host "Platform : $Platform"
Write-Host "Ref      : $Ref ($headCommit)"
if ($tag) {
    Write-Host "Tag      : $tag"
}
Write-Host "Contents : $($entries.Count) files, $sizeInMegabytes MB"
Write-Host "SHA256   : $hash"
Write-Host "Checksum : $checksumPath"
Write-Host "Verified : $($platformRequired.Count) required files present, $($RequiredPrefixes.Count) required directories non-empty, $($ForbiddenPatterns.Count) forbidden patterns absent"
if ($pendingChanges.Count -gt 0 -and $Ref -eq "HEAD") {
    Write-Warning "The working tree has uncommitted changes. The archive contains the committed state of HEAD only; commit first if you meant to ship them."
}
Write-Host ""
if ($Platform -eq "all") {
    Write-Host "Next: attach this file to the GitHub release for v$version. The website's two download buttons serve the -Platform windows / -Platform macos archives instead."
}
else {
    Write-Host "Next: copy this archive to the website's download/ directory -- that is what the site's $Platform button serves."
}
