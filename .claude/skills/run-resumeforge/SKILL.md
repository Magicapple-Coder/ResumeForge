---
name: run-resumeforge
description: Use when asked to "启动 ResumeForge", "跑一下这个项目", "看看界面/截图", "验证一下改动", "run ResumeForge", "start the app", "screenshot the UI", "drive the app", or when a frontend/backend change needs verifying in the RUNNING app instead of only in tests. Covers starting the app with the project launcher, taking headless-browser screenshots of real routes, rendering an isolated component, and calling the API.
---

# 运行并驱动 ResumeForge

ResumeForge 是 FastAPI + React 的本地应用：后端 127.0.0.1:8005，前端 Vite 5173（通过代理访问后端）。
本 skill 的价值不在"怎么启动"——那是启动器的事——而在**怎么看见并操作正在运行的应用**：截图真实页面、
隔离渲染单个组件、调接口。这三件事在测试里做不到。

**所有路径相对于仓库根目录** `D:\ResumeForge`。

## 启动（生命周期）

生命周期交给项目自己的启动器，**不要**把启动器嵌套进别的脚本里调用（原因见 Gotchas）：

```powershell
# 改了后端代码必须先 stop：启动器检测到后端已在运行会直接跳过，不会加载新代码
.\scripts\Stop-ResumeForge.ps1
.\scripts\Start-ResumeForge.ps1 -NoBrowser
```

`-NoBrowser` 避免弹出浏览器窗口。只想确认状态时用驱动：

```powershell
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 status
```

## 驱动（agent 主力路径）

驱动脚本 `.claude\skills\run-resumeforge\driver.ps1`，四个命令，全部要求应用已在运行：

```powershell
# 1. 状态：两个服务是否就绪
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 status

# 2. 截图真实页面（前端路由），默认落到 %TEMP%\resumeforge-shots\
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 shot /settings
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 shot /jobs

# 3. 隔离渲染单个组件：临时页面经 Vite 导入 src 下的真实组件，渲染后截图
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 component components/settings/DataBackupCard.tsx
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 component components/settings/DataBackupCard.tsx -Json '{"preview":null}'
# 渲染具名导出（默认导出之外的组件）用 path#ExportName 语法
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 component "features/assistant/components/AssistantMessageContent.tsx#MessageToolCalls" -Json '{"calls":[]}'

# 4. 调接口：状态码 + 响应体（中文已正确解码）
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 api /api/jobs
powershell.exe -NoProfile -File .\.claude\skills\run-resumeforge\driver.ps1 api /api/jobs -Method POST -Json '{"title":"测试岗位"}'
```

命令会打印截图的**绝对路径**，紧接着用 Read 工具把它读出来看——不要只看"截图成功"就当作验证通过。
`shot` 支持 `-Width/-Height/-Budget`（默认 1280x900 / 12000ms）。

`component` 的 `-Json` 是传给组件的 props；组件若需要回调函数，传 `null` 即可（只是渲染，不会触发）。
需要 API 数据的整页组件用 `shot` 打真实路由，而不是 `component`。

## 测试与静态检查

按 `AGENTS.md` 的"本项目验证命令"，不要另立一套：

```powershell
cd backend; $env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe -m pytest --cov=app --cov-config=..\pyproject.toml
.venv\Scripts\python.exe -m ruff check .

cd ..\frontend
npm test -- --maxWorkers=2
npm run typecheck; npm run lint; npm run format:check; npm run build
```

## Gotchas

**改完后端代码必须显式重启。** 启动器发现后端健康就直接跳过，你以为加载了新代码，其实还是旧进程——本项目已经因此误判过一次"功能没实现"。

**无头截图必须在浏览器已打开时用 `Start-Process`。** 用户开着 Chrome 时，`& chrome.exe --headless --screenshot=...` 会被静默移交给那个实例：无输出、无文件、`$LASTEXITCODE` 为空，看起来像命令没执行。驱动里用的是 `Start-Process -ArgumentList <数组>` + 独立 `--user-data-dir`，才真正起一个 headless 实例。Edge 同理（用户也常开着）。

**`.ps1` 文件保持纯 ASCII。** Windows PowerShell 5.1 把**无 BOM** 的 UTF-8 脚本按 ANSI/GBK 读，中文注释会导致解析失败，而 PowerShell 7 读同一文件完全正常——只在其中一个 shell 上炸。驱动脚本因此只有英文注释。

**接口返回的中文在 PS 5.1 下会乱码。** FastAPI 的 `application/json` 不带 charset，PS 5.1 回退到 Latin-1。驱动已做 UTF-8 重解码；自己写脚本时注意同样的坑。

**不要把启动器嵌套进脚本调用。** 启动器派生出的应用进程会继承调用者的 stdout 句柄，导致调用者永远等不到 EOF——表现为"重启成功了但脚本不返回"。生命周期请直接跑启动器。

**临时探针页面绝不能留在仓库里。** `component` 会写 `frontend\_probe.html`（Vite 从项目根提供），驱动在 `finally` 里把它**移入回收站**（项目约定不做永久删除）。若中途被强杀，手动确认该文件不存在。

**Windows 文件锁。** 任何需要替换数据库文件的操作（如数据恢复），必须先 `engine.dispose()`；测试里则是先 `db_session.close()`，否则 `os.replace` 报 `WinError 5`。

## 故障排查

| 现象 | 原因与处理 |
|---|---|
| `shot` 报 `Screenshot failed (exit N)` | 看它打印的浏览器日志路径；多半是 Chrome 被移交给了已运行实例，确认驱动是最新版本 |
| `status` 两个都是 `False` | 应用没在跑，先执行上面的启动器命令 |
| 前端起来了但页面空白/报错 | `runtime\frontend.stderr.log`；后端日志在 `runtime\backend.stderr.log`，AI 相关失败原因（如"已回退本地解析"）只在这里，界面上看不到 |
| 启动器说 "Backend is already running" 但代码没生效 | 预期的：必须先 `stop` 再 `start` |
| `component` 渲染空白 | 组件可能需要 context 或 API 数据；改用 `shot` 打真实路由 |
