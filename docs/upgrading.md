# 升级与数据安全

ResumeForge 是本地单用户应用。代码、Python/Node 依赖和本地业务数据分开管理：Git 只跟踪代码和配置示例，用户数据库位于 `backend/data/`，不会被正常的 `git pull` 覆盖。

## 推荐升级流程（Git 安装）

升级前先关闭正在运行的后端和前端进程，在项目目录执行：

### Windows PowerShell

```powershell
Set-Location "C:\path\to\ResumeForge"
cd backend
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe scripts\backup_database.py
cd ..
git status
git pull --ff-only

cd backend
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm ci
```

### macOS / Linux

```bash
cd ~/ResumeForge/backend
export PYTHONUTF8=1
.venv/bin/python scripts/backup_database.py
cd ..
git status
git pull --ff-only

cd backend
.venv/bin/python -m pip install -r requirements.txt
cd ../frontend
npm ci
```

依赖安装完成后，Windows 用户可在项目根目录双击 `start.cmd`，它会启动前后端并自动打开页面。需要关闭服务时双击 `stop.cmd`。启动器只会终止自己记录且校验通过的 ResumeForge 进程。

一键启动器默认使用后端端口 8005、前端端口 5173；若端口冲突，可通过 `-BackendPort` 或 `-FrontendPort` 参数指定其他端口。手动启动示例中的后端端口 8000 是开发默认值，与一键启动器互不冲突。

启动器会在 `frontend/` 目录执行 npm 安装，因此从资源管理器双击启动时不会因为当前工作目录不同而误报缺少 `package-lock.json`。仓库包含锁文件时使用 `npm ci`；旧压缩包缺少锁文件时会回退到一次 `npm install`。

首次创建环境时，启动器会探测现有 Python 3.10+ 和 Node.js 20.19.0+/npm，满足要求时直接复用。缺少 Python 时优先通过 Windows `winget` 进行用户级静默安装，再回退到固定版本且校验 SHA-256 的 Python 官方 x64 安装器；缺少 Node.js/npm 时同样先使用 `winget`，再回退到校验过的 Node.js 官方 x64/ARM64 便携 ZIP，并解压到 `runtime/tools/`。自动准备需要网络，不会触碰数据库或 `.env`；如果 winget、网络、系统架构或权限不满足条件，启动器会停止并给出手动安装指引。升级代码时 `runtime/` 不受正常 `git pull` 影响；即使便携 Node 目录被手动删除，下次启动也只会重新准备运行时，不影响业务数据。

开发、排错或 macOS/Linux 环境仍可分别启动后端与前端，并确认健康检查正常：

```powershell
# 终端 1（Windows）
cd backend
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 终端 2
cd frontend
npm run dev
```

macOS/Linux 将后端 Python 路径替换为 `.venv/bin/python`；前端命令不变。

`git pull --ff-only` 如果发现你改过本地代码会停止，而不会自动覆盖修改；先保存或处理本地改动，再重新执行。不要使用 `git clean -fdx` 清理项目，否则会删除被忽略的数据库和 `.env`。

## 数据迁移与回滚

- 后端启动时会自动执行 `backend/migrations/` 中尚未应用的 Alembic migration。
- 检测到已有数据且存在待迁移版本时，程序会先在 `backend/data/backups/` 创建一致性 SQLite 备份。
- 当前迁移链中的 `0003_job_additional_info` 会为旧岗位补充空的“其他信息”，`0004_resume_favorite` 会把旧简历收藏状态初始化为未收藏，`0005_chat_assistant` 新增助手会话和消息表，`0006_chat_conversation_flags` 新增置顶/收藏字段且不会重建会话父表；这些升级不会改写原有岗位、资料、简历正文或助手消息。
- 自动备份不是替代品；升级前仍应把 `backend/data/resume_forge.db` 和 `.env` 复制到项目目录之外，并对备份设置访问权限。
- 升级启动失败时，先停止服务，保留错误日志；不要删除原数据库。可从升级前备份恢复数据库，再检出上一个稳定版本启动。

不要为了切回旧代码直接运行上述 revision 的 `downgrade`：降级 `0005` 会删除助手会话历史，降级 `0004` 会删除简历收藏状态，降级 `0003` 会删除岗位“其他信息”。需要保留这些数据时，应停止服务并恢复升级前备份，再检出匹配的旧版本代码。

示例回滚步骤（请把路径换成自己的备份文件）：

```powershell
$backup = "backend\data\backups\resume_forge-YYYYMMDD-HHMMSS-ffffff.db"
Copy-Item $backup backend\data\resume_forge.db -Force
git checkout <previous-stable-tag-or-commit>  # 例如已发布的 v0.1.0 标签或对应提交
```

将占位符替换为你要回滚到的实际稳定标签或提交；发布新版本时应为稳定版本创建 Git 标签（本次为 `v0.2.0`），并在 `CHANGELOG.md` 标出迁移和兼容性要求。如果数据库已经执行了不可逆的迁移，必须先阅读对应 revision 的降级说明；不要把新版本数据库直接交给旧版本使用。

改用回滚也可以走应用内：在 **设置 → 数据备份与恢复** 里导入之前导出的备份包，程序会先把当前数据库
自动备份到 `backend/data/backups/` 再替换，所以这一步本身也是可回滚的。注意备份包记录着导出时的
Alembic revision，**旧版本无法导入新版本导出的备份**，会明确拒绝并提示先升级应用。

设置页的「最大输出 Token」在新版本中可以用 `0` 表示“不限制”，但旧版本会把 `0` 判定为非法值并把整份模型配置（含 Base URL、模型名称和 API Key）重置为默认值。回退到旧版本之前，请先在设置页把该字段改回 256 以上的具体数值。这一项不涉及数据库结构变更。

## 使用压缩包更新

如果不使用 Git，请先退出程序并备份 `backend/data/` 和 `backend/.env`，再把新版本解压到新的目录。安装新版本依赖后，将旧目录的 `backend/data/` 和 `backend/.env` 复制到新目录；不要覆盖新版本的代码文件，也不要把数据库提交到公开仓库。

## 保留哪些文件

升级时需要保留：

- `backend/data/resume_forge.db` 及 `backend/data/backups/`；
- `backend/.env`（如果修改过服务端配置）；
- 个人导出的简历和外部备份文件。

不需要也不应复制：

- `backend/.venv/`、`frontend/node_modules/` 和 `frontend/dist/`；
- 测试缓存、日志和临时文件。

依赖版本变化后重新执行安装命令，比复制旧虚拟环境更可靠。
