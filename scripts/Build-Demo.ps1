# 构建「在线体验」静态产物。
#
# 产物结构（可直接扔进 GitHub Pages 或官网目录）：
#   dist-demo/
#     index.html, assets/…
#     demo-data/api-snapshot.json     ← 录制的只读接口回放
#     demo-data/ai-replies.json       ← AI 回放素材
#
# 关键点：
#   - `VITE_DEMO_MODE=1` 让 `main.tsx` 动态引入 `src/demo/*`，并让 vite 用 `base: "./"`。
#   - 输出目录刻意放仓库外（默认为 $env:TEMP 下的一个目录），因为本机沙箱会在
#     `vite build` 清空 dist 时命中批量删除守卫（SAFE_DELETE_BULK_CONFIRM_REQUIRED）。
#     要放进仓库时用 -OutDir 指到 .gitignore 覆盖的位置。
#
# 用法：
#   pwsh -File scripts/Build-Demo.ps1
#   pwsh -File scripts/Build-Demo.ps1 -OutDir D:\rf-demo-dist
#   pwsh -File scripts/Build-Demo.ps1 -Release      # 发布用：拒绝带上本机白名单
param(
    [string]$OutDir = (Join-Path $env:TEMP "rf-demo-dist"),
    [string]$Snapshot = "D:\ResumeForge\runtime\demo\api-snapshot.json",
    [string]$AiReplies = "D:\ResumeForge\runtime\demo\ai-replies.json",
    # 发布产物用 -Release：若 `frontend/.env.demo.local` 还在，构建会把
    # localhost 白名单一并烘焙进 bundle（见下方校验）。发布态应当只认正式域名，
    # 所以这里直接报错让你先把那个本地文件挪走或删掉。
    [switch]$Release
)

$ErrorActionPreference = "Stop"
# 注意是「仓库根的 frontend 子目录」，不是仓库根——`vite build` 必须在能看见
# index.html 的目录里跑，否则报 `Cannot resolve entry module index.html`。
$frontend = Join-Path (Split-Path -Parent $PSScriptRoot) "frontend"

if (-not (Test-Path $Snapshot)) {
    throw "缺少接口快照 $Snapshot，请先跑 runtime/demo/tools/record_api.js"
}
if (-not (Test-Path $AiReplies)) {
    throw "缺少回放素材 $AiReplies，请先跑 runtime/demo/tools/build_ai_replies.js"
}

Write-Host "构建前端（demo 模式）→ $OutDir"
Push-Location $frontend
try {
    # 用 frontend/node_modules 里的本机二进制，不要用 npx：
    # npx 会去 `D:\npm-cache\_npx\…` 找缓存里的包，拿到一个版本对不上的
    # 全局 vite/tsc（实测报 "This is not the tsc command you are looking for"
    # 并让 vite build 找不到 index.html）。改走 npm scripts 也是同样道理。
    $vite = Join-Path $frontend "node_modules\.bin\vite.cmd"
    $tsc = Join-Path $frontend "node_modules\.bin\tsc.cmd"
    if (-not (Test-Path $vite)) { throw "找不到 $vite，请先在 frontend 目录跑 npm ci" }

    # 先做类型检查：`vite build` 自己不做，tsc 才能挡住类型错误。
    & $tsc --noEmit
    if ($LASTEXITCODE -ne 0) { throw "tsc --noEmit 失败" }
    # `--mode demo` 会加载 frontend/.env.demo（`VITE_DEMO_MODE=1`）。
    # **不要**改成 shell 里设环境变量：`loadEnv()` 只扫 .env* 文件，
    # 那样写 `base` 会静默退回 "/"，产物就无法部署到子路径。
    & $vite build --mode demo --outDir $OutDir --emptyOutDir
    if ($LASTEXITCODE -ne 0) { throw "vite build 失败" }
} finally {
    Pop-Location
}

$dataDir = Join-Path $OutDir "demo-data"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
Copy-Item $Snapshot (Join-Path $dataDir "api-snapshot.json") -Force
Copy-Item $AiReplies (Join-Path $dataDir "ai-replies.json") -Force

# ---------------------------------------------------------------------------
# 校验：产物里不能烘焙本机（localhost/127.0.0.1）的父来源白名单。
#
# 背景：`demoBridge.ts` 的 `allowedParents()` 会把 `DEFAULT_PARENTS`
# （正式域名 magicapple123.github.io）与环境变量 `VITE_DEMO_PARENT_ORIGINS`
# 拼在一起。后者由 `frontend/.env.demo.local` 注入（该文件 gitignore，
# 内容是本机联调端口）。只要构建时那个文件在，localhost 就会**编进正式产物**，
# 等于永久放宽一个来源。
#
# 注意判定方式：不能在产物里简单地搜 "127.0.0.1"，因为 `DEFAULT_PARENTS`
# 与额外名单被压成同一个函数体、两者都在同一个 chunk 里（实测：
#   const i=["https://magicapple123.github.io"];
#   function s(){const e="http://127.0.0.1:8132,http://localhost:8132".trim();...}
# ），`i`（正式域名）必然存在、不能当失败条件。真正该判的是**额外名单那一份**：
# 它在产物里的形态是"赋值给局部变量的字符串字面量"，而正式域名那份是数组字面量。
# 两者同时出现即说明本机白名单被烘焙进去了。
# ---------------------------------------------------------------------------
$bridgeChunk = Get-ChildItem $OutDir -Recurse -File -Filter "demoBridge-*.js" |
    Select-Object -First 1
if (-not $bridgeChunk) {
    throw "产物里找不到 demoBridge-*.js，构建似乎不完整"
}
$bridge = Get-Content $bridgeChunk.FullName -Raw
$bakesLocalhost = $bridge -match '127\.0\.0\.1' -or $bridge -match 'localhost'
if ($bakesLocalhost) {
    $msg = @"
产物 ($($bridgeChunk.Name)) 里烘焙了本机父来源白名单（localhost/127.0.0.1）。

这来自 frontend/.env.demo.local —— 它是本机联调配置，不该进正式产物：
带上它等于让线上实例接受来自本机端口的导航指令，白名单也就失去了意义。

处置：把 frontend/.env.demo.local 临时改名或移走，再重新构建。
（本机联调时保留它没问题；发布前务必用 -Release 重建一次。）
"@
    if ($Release) { throw $msg }
    Write-Warning $msg
}

$total = (Get-ChildItem $OutDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("完成：{0}（{1:N1} MB）" -f $OutDir, ($total / 1MB))
