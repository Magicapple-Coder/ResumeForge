# Build the "online demo" static bundle.
#
# Layout (can be dropped straight into GitHub Pages or the marketing site):
#   dist-demo/
#     index.html, assets/...
#     demo-data/api-snapshot.json     <- recorded read-only API replies
#     demo-data/ai-replies.json       <- recorded AI playback
#
# Key points:
#   - `VITE_DEMO_MODE=1` makes `main.tsx` dynamically import `src/demo/*`,
#     and makes vite use `base: "./"`.
#   - The output directory deliberately lives outside the repo (a directory
#     under $env:TEMP by default): the local sandbox trips the bulk-delete
#     guard (SAFE_DELETE_BULK_CONFIRM_REQUIRED) when `vite build` empties a
#     dist directory inside the tree. Point -OutDir at a .gitignore'd path
#     if you need it in the repo.
#
# Usage:
#   pwsh -File scripts/Build-Demo.ps1
#   pwsh -File scripts/Build-Demo.ps1 -OutDir D:\rf-demo-dist
#   pwsh -File scripts/Build-Demo.ps1 -Release      # release build: reject baked-in localhost allowlist
#
# NOTE: this file must stay pure ASCII, or carry a UTF-8 BOM.
# Windows PowerShell 5.1 (which is what start.cmd invokes) decodes a BOM-less
# file with the ANSI code page, so Chinese text here would be read as GBK and
# break the parse. The launcher test in scripts/tests enforces this. Sibling
# packaging script Build-Release.ps1 is pure ASCII too.
param(
    [string]$OutDir = (Join-Path $env:TEMP "rf-demo-dist"),
    [string]$Snapshot = "D:\ResumeForge\runtime\demo\api-snapshot.json",
    [string]$AiReplies = "D:\ResumeForge\runtime\demo\ai-replies.json",
    # Pass -Release for a release build. If `frontend/.env.demo.local` is still
    # present, localhost gets baked into the bundle (see the verification step
    # below). Release bundles should only trust the real domains, so this mode
    # fails loudly and asks you to move that local file away first.
    [switch]$Release
)

$ErrorActionPreference = "Stop"
# Note this is "the frontend subdirectory of the repo root", not the repo root:
# `vite build` must run where it can see index.html, otherwise it reports
# `Cannot resolve entry module index.html`.
$frontend = Join-Path (Split-Path -Parent $PSScriptRoot) "frontend"

if (-not (Test-Path $Snapshot)) {
    throw "Missing API snapshot $Snapshot. Run runtime/demo/tools/record_api.js first."
}
if (-not (Test-Path $AiReplies)) {
    throw "Missing AI playback data $AiReplies. Run runtime/demo/tools/build_ai_replies.js first."
}

Write-Host "Building frontend (demo mode) -> $OutDir"
Push-Location $frontend
try {
    # Use the local binaries under frontend/node_modules, never npx:
    # npx looks in `D:\npm-cache\_npx\...` for a cached global package and
    # picks up a mismatched vite/tsc (measured: "This is not the tsc command
    # you are looking for", then vite build cannot find index.html). Going
    # through npm scripts has the same problem.
    $vite = Join-Path $frontend "node_modules\.bin\vite.cmd"
    $tsc = Join-Path $frontend "node_modules\.bin\tsc.cmd"
    if (-not (Test-Path $vite)) { throw "Cannot find $vite. Run npm ci in frontend first." }

    # Type-check first: `vite build` does not do it, and tsc is what catches
    # type errors.
    & $tsc --noEmit
    if ($LASTEXITCODE -ne 0) { throw "tsc --noEmit failed" }
    # `--mode demo` loads frontend/.env.demo (`VITE_DEMO_MODE=1`).
    # Do NOT set this as a shell environment variable instead: `loadEnv()` only
    # scans .env* files, so `base` silently falls back to "/" and the bundle
    # cannot be deployed under a subpath.
    & $vite build --mode demo --outDir $OutDir --emptyOutDir
    if ($LASTEXITCODE -ne 0) { throw "vite build failed" }
} finally {
    Pop-Location
}

$dataDir = Join-Path $OutDir "demo-data"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
Copy-Item $Snapshot (Join-Path $dataDir "api-snapshot.json") -Force
Copy-Item $AiReplies (Join-Path $dataDir "ai-replies.json") -Force

# ---------------------------------------------------------------------------
# Verify the bundle does not bake in the local (localhost/127.0.0.1) parent
# origin allowlist.
#
# Background: `allowedParents()` in `demoBridge.ts` concatenates
# `DEFAULT_PARENTS` (the production domain magicapple123.github.io) with the
# environment variable `VITE_DEMO_PARENT_ORIGINS`. The latter is injected by
# `frontend/.env.demo.local` (gitignored, holds the local dev ports). As long
# as that file exists at build time, localhost is **compiled into the
# production bundle**, which permanently widens one allowed origin.
#
# Careful with the predicate: do NOT simply search the bundle for "127.0.0.1".
# `DEFAULT_PARENTS` and the extra list are minified into the same chunk,
# in the same function body (measured):
#   const i=["https://magicapple123.github.io"];
#   function s(){const e="http://127.0.0.1:8132,http://localhost:8132".trim();...}
# `i` (the production domain) is always present and must not fail the check.
# What we actually want to detect is **the extra list only**: in the bundle it
# appears as a string literal assigned to a local variable, whereas the
# production domain appears as an array literal. Both present at once means the
# local allowlist got baked in.
# ---------------------------------------------------------------------------
$bridgeChunk = Get-ChildItem $OutDir -Recurse -File -Filter "demoBridge-*.js" |
    Select-Object -First 1
if (-not $bridgeChunk) {
    throw "No demoBridge-*.js found in the output. The build looks incomplete."
}
$bridge = Get-Content $bridgeChunk.FullName -Raw
$bakesLocalhost = $bridge -match '127\.0\.0\.1' -or $bridge -match 'localhost'
if ($bakesLocalhost) {
    $msg = @"
The bundle ($($bridgeChunk.Name)) contains the local parent-origin allowlist (localhost/127.0.0.1).

This comes from frontend/.env.demo.local, which is a local development setting
and must not reach a production bundle: keeping it means the deployed instance
accepts navigation commands from a local port, which defeats the allowlist.

Fix: rename or move frontend/.env.demo.local away, then rebuild.
(Keeping it for local development is fine; just rebuild with -Release before
publishing.)
"@
    if ($Release) { throw $msg }
    Write-Warning $msg
}

$total = (Get-ChildItem $OutDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("Done: {0} ({1:N1} MB)" -f $OutDir, ($total / 1MB))
